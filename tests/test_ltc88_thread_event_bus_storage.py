from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC88ThreadEventBusStorageTests(unittest.TestCase):
    def test_thread_event_create_and_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc88.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-8801, "g")
                q = storage.create_question(
                    question_id="q1",
                    thread_id="t1",
                    team_id=int(group.team_id or 0),
                    created_by_user_id=700,
                    target_team_role_id=None,
                    text="hello",
                    status="accepted",
                )
                e1 = storage.create_thread_event(
                    team_id=q.team_id,
                    thread_id=q.thread_id,
                    event_type="thread.message.created",
                    author_type="user",
                    direction="question",
                    question_id=q.question_id,
                    idempotency_key="evt-key-1",
                )
                e2 = storage.create_thread_event(
                    team_id=q.team_id,
                    thread_id=q.thread_id,
                    event_type="thread.message.created",
                    author_type="user",
                    direction="question",
                    question_id=q.question_id,
                    idempotency_key="evt-key-1",
                )
            self.assertEqual(e1.event_id, e2.event_id)
            items = storage.list_thread_events(thread_id="t1", limit=10)
            self.assertEqual(len(items), 1)
            by_event = storage.list_thread_events(event_id=e1.event_id, limit=10)
            self.assertEqual(len(by_event), 1)
            self.assertEqual(by_event[0].event_id, e1.event_id)

    def test_event_subscription_upsert_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc88.sqlite3")
            with storage.transaction(immediate=True):
                first = storage.upsert_event_subscription(
                    scope="team",
                    scope_id="1",
                    interface_type="telegram",
                    target_id="-1001",
                    mode="mirror",
                    is_active=True,
                )
                second = storage.upsert_event_subscription(
                    scope="team",
                    scope_id="1",
                    interface_type="telegram",
                    target_id="-1001",
                    mode="mirror",
                    is_active=False,
                    options_json='{"mute":true}',
                )
            self.assertEqual(first.subscription_id, second.subscription_id)
            active = storage.list_event_subscriptions(scope="team", scope_id="1", active_only=True)
            self.assertEqual(active, [])
            all_items = storage.list_event_subscriptions(scope="team", scope_id="1", active_only=False)
            self.assertEqual(len(all_items), 1)
            self.assertFalse(all_items[0].is_active)
            self.assertEqual(all_items[0].options_json, '{"mute":true}')

    def test_event_delivery_enqueue_pending_retry_and_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc88.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-8802, "g")
                q = storage.create_question(
                    question_id="q2",
                    thread_id="t2",
                    team_id=int(group.team_id or 0),
                    created_by_user_id=700,
                    target_team_role_id=None,
                    text="hello",
                    status="accepted",
                )
                ev = storage.create_thread_event(
                    team_id=q.team_id,
                    thread_id=q.thread_id,
                    event_type="thread.message.created",
                    author_type="user",
                    direction="question",
                    question_id=q.question_id,
                )
                d1 = storage.enqueue_event_delivery(
                    event_id=ev.event_id,
                    interface_type="telegram",
                    target_id="-1002",
                    idempotency_key="del-key-1",
                )
                d2 = storage.enqueue_event_delivery(
                    event_id=ev.event_id,
                    interface_type="telegram",
                    target_id="-1002",
                    idempotency_key="del-key-1",
                )
                self.assertEqual(d1.delivery_id, d2.delivery_id)
                pending = storage.list_pending_event_deliveries(limit=10)
                self.assertEqual(len(pending), 1)
                retry = storage.mark_event_delivery_retry(
                    d1.delivery_id,
                    error_code="network_error",
                    error_message="temporary",
                    retry_delay_sec=0,
                )
                self.assertIsNotNone(retry)
                self.assertEqual(retry.status if retry else None, "retry_scheduled")
                delivered = storage.mark_event_delivery_delivered(d1.delivery_id)
                self.assertIsNotNone(delivered)
                self.assertEqual(delivered.status if delivered else None, "delivered")
                pending_after = storage.list_pending_event_deliveries(limit=10)
                self.assertEqual(pending_after, [])
                self.assertEqual(storage.count_event_deliveries(status="delivered"), 1)

    def test_thread_event_fanout_enqueues_primary_and_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc88.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-8803, "g")
                team_id = int(group.team_id or 0)
                storage.upsert_event_subscription(
                    scope="thread",
                    scope_id="t3",
                    interface_type="telegram",
                    target_id="t3",
                    mode="mirror",
                    is_active=True,
                )
                storage.upsert_event_subscription(
                    scope="team",
                    scope_id=str(team_id),
                    interface_type="webhook",
                    target_id="team-3",
                    mode="mirror",
                    is_active=True,
                )
                q = storage.create_question(
                    question_id="q3",
                    thread_id="t3",
                    team_id=team_id,
                    created_by_user_id=700,
                    target_team_role_id=None,
                    text="hello",
                    status="accepted",
                )
                storage.create_thread_event(
                    team_id=q.team_id,
                    thread_id=q.thread_id,
                    event_type="thread.message.created",
                    author_type="user",
                    direction="question",
                    origin_interface="telegram",
                    question_id=q.question_id,
                )
                pending = storage.list_pending_event_deliveries(limit=10)
                keys = {(item.interface_type, item.target_id) for item in pending}
                self.assertEqual(keys, {("telegram", "t3"), ("webhook", "team-3")})

    def test_claim_and_dlq_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc88.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-8804, "g")
                q = storage.create_question(
                    question_id="q4",
                    thread_id="t4",
                    team_id=int(group.team_id or 0),
                    created_by_user_id=700,
                    target_team_role_id=None,
                    text="hello",
                    status="accepted",
                )
                ev = storage.create_thread_event(
                    team_id=q.team_id,
                    thread_id=q.thread_id,
                    event_type="thread.message.created",
                    author_type="user",
                    direction="question",
                    question_id=q.question_id,
                )
                d1 = storage.enqueue_event_delivery(
                    event_id=ev.event_id,
                    interface_type="telegram",
                    target_id="-1004",
                )
                claimed = storage.claim_pending_event_deliveries(limit=10, lease_owner="worker-1", lease_ttl_sec=5)
                self.assertEqual([item.delivery_id for item in claimed], [d1.delivery_id])
                dlq = storage.mark_event_delivery_dlq(
                    d1.delivery_id,
                    error_code="delivery_failed",
                    error_message="boom",
                )
                self.assertIsNotNone(dlq)
                self.assertEqual(dlq.status if dlq else None, "failed_dlq")
                pending_after = storage.list_pending_event_deliveries(limit=10)
                self.assertEqual(pending_after, [])


if __name__ == "__main__":
    unittest.main()
