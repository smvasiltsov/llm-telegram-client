from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.interfaces.api.thread_event_outbox_dispatcher import (
    TelegramBotApiDeliveryAdapter,
    ThreadEventOutboxDispatcher,
)
from app.storage import Storage


class _CollectAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def deliver(self, *, event, delivery, idempotency_key: str) -> None:  # noqa: ANN001
        self.calls.append((str(event.event_id), str(delivery.target_id), str(idempotency_key)))


class _FailAdapter:
    async def deliver(self, *, event, delivery, idempotency_key: str) -> None:  # noqa: ANN001
        raise RuntimeError("network down")


class _MetricsCapture:
    def __init__(self) -> None:
        self.increments: list[tuple[str, dict | None, int | None]] = []
        self.observes: list[tuple[str, dict | None, float]] = []

    def increment(self, name: str, *, labels=None, value: int = 1) -> None:  # noqa: ANN001
        self.increments.append((str(name), labels, int(value)))

    def observe_ms(self, name: str, *, value_ms: float, labels=None) -> None:  # noqa: ANN001
        self.observes.append((str(name), labels, float(value_ms)))


class LTC89ThreadEventOutboxDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Storage(Path(self._tmp.name) / "ltc89.sqlite3")
        with self.storage.transaction(immediate=True):
            group = self.storage.upsert_group(-8901, "g")
            self.team_id = int(group.team_id or 0)
            self.question = self.storage.create_question(
                question_id="q89",
                thread_id="t89",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=None,
                text="hello",
                status="accepted",
            )

    async def _wait_for_delivery_status(self, delivery_id: int, status: str, timeout_sec: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            item = self.storage.get_event_delivery(delivery_id)
            if item is not None and item.status == status:
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"delivery {delivery_id} did not reach status={status}")

    async def test_dispatcher_delivers_primary_and_subscriber_once(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.upsert_event_subscription(
                scope="team",
                scope_id=str(self.team_id),
                interface_type="mirror",
                target_id="mirror-team",
                mode="mirror",
                is_active=True,
            )
            event = self.storage.create_thread_event(
                team_id=self.team_id,
                thread_id=self.question.thread_id,
                event_type="thread.message.created",
                author_type="user",
                direction="question",
                origin_interface="telegram",
                question_id=self.question.question_id,
            )
            pending = self.storage.list_pending_event_deliveries(limit=20)
            by_key = {(item.interface_type, item.target_id): item.delivery_id for item in pending}
            self.assertIn(("telegram", "t89"), by_key)
            self.assertIn(("mirror", "mirror-team"), by_key)

        primary = _CollectAdapter()
        mirror = _CollectAdapter()
        metrics = _MetricsCapture()
        runtime = SimpleNamespace(
            storage=self.storage,
            metrics_port=metrics,
            thread_event_delivery_adapters={"telegram": primary, "mirror": mirror},
        )
        dispatcher = ThreadEventOutboxDispatcher(
            runtime=runtime,
            poll_interval_sec=0.05,
            retry_backoff_base_sec=0,
        )
        await dispatcher.start()
        self.addAsyncCleanup(dispatcher.stop)

        await self._wait_for_delivery_status(by_key[("telegram", "t89")], "delivered")
        await self._wait_for_delivery_status(by_key[("mirror", "mirror-team")], "delivered")
        await asyncio.sleep(0.2)

        self.assertEqual(len(primary.calls), 1)
        self.assertEqual(len(mirror.calls), 1)
        self.assertEqual(primary.calls[0][0], event.event_id)
        self.assertEqual(mirror.calls[0][0], event.event_id)
        self.assertTrue(any(name == "deliveries_ok" for name, _, _ in metrics.increments))
        self.assertTrue(any(name == "delivery_lag_ms" for name, _, _ in metrics.observes))
        self.assertTrue(any(name == "dlq_size" for name, _, _ in metrics.observes))

    async def test_dispatcher_retries_and_moves_to_dlq(self) -> None:
        with self.storage.transaction(immediate=True):
            event = self.storage.create_thread_event(
                team_id=self.team_id,
                thread_id=self.question.thread_id,
                event_type="thread.message.created",
                author_type="user",
                direction="question",
                origin_interface="failbus",
                question_id=self.question.question_id,
            )
            delivery = self.storage.enqueue_event_delivery(
                event_id=event.event_id,
                interface_type="failbus",
                target_id="fail-target",
                max_attempts=2,
            )

        metrics = _MetricsCapture()
        runtime = SimpleNamespace(
            storage=self.storage,
            metrics_port=metrics,
            thread_event_delivery_adapters={"failbus": _FailAdapter()},
        )
        dispatcher = ThreadEventOutboxDispatcher(
            runtime=runtime,
            poll_interval_sec=0.05,
            retry_backoff_base_sec=0,
            retry_backoff_max_sec=1,
        )
        await dispatcher.start()
        self.addAsyncCleanup(dispatcher.stop)

        await self._wait_for_delivery_status(delivery.delivery_id, "failed_dlq", timeout_sec=4.0)
        item = self.storage.get_event_delivery(delivery.delivery_id)
        self.assertIsNotNone(item)
        self.assertEqual(item.status if item else None, "failed_dlq")
        self.assertEqual(item.attempt_count if item else None, 2)
        self.assertTrue(any(name == "deliveries_failed" for name, _, _ in metrics.increments))
        self.assertTrue(any(name == "dlq_size" for name, _, _ in metrics.observes))

    async def test_telegram_adapter_formats_sender_and_skips_duplicate_child_question(self) -> None:
        sent_payloads: list[dict[str, object]] = []

        class _FakeResponse:
            def __init__(self) -> None:
                self.status_code = 200
                self.text = "ok"

            def json(self):
                return {"ok": True}

        class _FakeClient:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                _ = (args, kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                _ = (exc_type, exc, tb)
                return False

            async def post(self, _url: str, json=None, headers=None):  # noqa: ANN001
                _ = headers
                sent_payloads.append(dict(json or {}))
                return _FakeResponse()

        fake_httpx = SimpleNamespace(AsyncClient=_FakeClient)
        with patch.dict(sys.modules, {"httpx": fake_httpx}):
            with self.storage.transaction(immediate=True):
                question = self.storage.create_question(
                    question_id="q89-role",
                    thread_id="t89-role",
                    team_id=self.team_id,
                    created_by_user_id=700,
                    target_team_role_id=None,
                    text="root",
                    status="answered",
                )
                answer = self.storage.create_answer(
                    answer_id="a89-role",
                    question_id=question.question_id,
                    thread_id=question.thread_id,
                    team_id=question.team_id,
                    team_role_id=None,
                    role_name="dev",
                    text="@ops check this",
                )
                role_answer_event = self.storage.create_thread_event(
                    team_id=self.team_id,
                    thread_id=question.thread_id,
                    event_type="thread.message.created",
                    author_type="role",
                    direction="answer",
                    origin_interface="telegram",
                    question_id=question.question_id,
                    answer_id=answer.answer_id,
                    payload_json='{"kind":"role-answer","text":"@ops check this","lineage":{"source_question_id":null,"parent_answer_id":null}}',
                )
                child_question_event = self.storage.create_thread_event(
                    team_id=self.team_id,
                    thread_id=question.thread_id,
                    event_type="thread.message.created",
                    author_type="role",
                    direction="question",
                    origin_interface="telegram",
                    question_id=question.question_id,
                    source_question_id=question.question_id,
                    parent_answer_id=answer.answer_id,
                    payload_json='{"kind":"child-question","text":"@ops check this","lineage":{"source_question_id":"q89-role","parent_answer_id":"a89-role"}}',
                )
                delivery1 = self.storage.enqueue_event_delivery(
                    event_id=role_answer_event.event_id,
                    interface_type="telegram",
                    target_id="-10089",
                )
                delivery2 = self.storage.enqueue_event_delivery(
                    event_id=child_question_event.event_id,
                    interface_type="telegram",
                    target_id="-10089",
                )

            adapter = TelegramBotApiDeliveryAdapter(bot_token="123:abc", storage=self.storage)
            await adapter.deliver(event=role_answer_event, delivery=delivery1, idempotency_key="k1")
            await adapter.deliver(event=child_question_event, delivery=delivery2, idempotency_key="k2")

        self.assertEqual(len(sent_payloads), 1)
        sent_text = str(sent_payloads[0].get("text") or "")
        self.assertIn("<b>dev</b>", sent_text)
        self.assertIn("\n\n", sent_text)


if __name__ == "__main__":
    unittest.main()
