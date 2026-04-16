from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import json
from html import escape as _html_escape
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

from app.application.contracts import NoopMetricsPort
from app.application.observability import correlation_scope, ensure_correlation_id
from app.models import EventDelivery, ThreadEvent

logger = logging.getLogger("api.thread_outbox")


class ThreadEventDeliveryAdapter(Protocol):
    async def deliver(self, *, event: ThreadEvent, delivery: EventDelivery, idempotency_key: str) -> None: ...


class LoggingThreadEventDeliveryAdapter:
    async def deliver(self, *, event: ThreadEvent, delivery: EventDelivery, idempotency_key: str) -> None:
        logger.info(
            "thread_outbox_delivered interface=%s target=%s event_id=%s thread_id=%s seq=%s idempotency_key=%s",
            delivery.interface_type,
            delivery.target_id,
            event.event_id,
            event.thread_id,
            event.seq,
            idempotency_key,
        )


class TelegramBotApiDeliveryAdapter:
    def __init__(self, *, bot_token: str, storage, timeout_sec: int = 10) -> None:
        token = str(bot_token or "").strip()
        if not token:
            raise ValueError("bot_token is required")
        self._bot_token = token
        self._storage = storage
        self._timeout_sec = max(1, int(timeout_sec))

    @staticmethod
    def _parse_payload(event: ThreadEvent) -> dict[str, object]:
        try:
            payload = json.loads(str(event.payload_json or "{}"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    def _build_text(self, event: ThreadEvent) -> str:
        payload_text = ""
        payload_kind = ""
        payload = self._parse_payload(event)
        payload_text = str(payload.get("text") or "").strip()
        payload_kind = str(payload.get("kind") or "").strip()
        if payload_kind == "user-question":
            # Initial human message is already present in Telegram chat.
            return ""
        if payload_kind == "child-question":
            parent_answer_id = str(payload.get("lineage", {}).get("parent_answer_id") if isinstance(payload.get("lineage"), dict) else "")
            if parent_answer_id:
                parent_answer = self._storage.get_answer(parent_answer_id)
                if parent_answer is not None:
                    if self._normalize_text(parent_answer.text) == self._normalize_text(payload_text):
                        # Do not duplicate mirrored role-answer and derived child-question.
                        return ""
        sender_name = self._resolve_sender_name(event=event, payload=payload)
        if sender_name:
            return f"<b>{_html_escape(sender_name)}</b>\n\n{_html_escape(payload_text)}"
        return _html_escape(payload_text)

    def _resolve_sender_name(self, *, event: ThreadEvent, payload: dict[str, object]) -> str:
        if event.answer_id:
            answer = self._storage.get_answer(str(event.answer_id))
            if answer is not None and str(answer.role_name or "").strip():
                return str(answer.role_name).strip()
        lineage = payload.get("lineage")
        if isinstance(lineage, dict):
            parent_answer_id = str(lineage.get("parent_answer_id") or "").strip()
            if parent_answer_id:
                parent_answer = self._storage.get_answer(parent_answer_id)
                if parent_answer is not None and str(parent_answer.role_name or "").strip():
                    return str(parent_answer.role_name).strip()
        return ""

    async def deliver(self, *, event: ThreadEvent, delivery: EventDelivery, idempotency_key: str) -> None:
        _ = idempotency_key
        text = self._build_text(event)
        if not text:
            return
        try:
            import httpx  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime dependency gap
            raise RuntimeError("telegram_delivery_httpx_missing") from exc
        try:
            chat_id = int(str(delivery.target_id))
        except Exception:
            raise RuntimeError(f"invalid_telegram_target:{delivery.target_id}") from None
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=float(self._timeout_sec)) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                    "parse_mode": "HTML",
                },
                headers={"X-Idempotency-Key": str(delivery.idempotency_key or "")},
            )
        if resp.status_code >= 300:
            raise RuntimeError(f"telegram_http_{resp.status_code}:{resp.text[:300]}")
        body = resp.json()
        if not isinstance(body, dict) or not bool(body.get("ok")):
            raise RuntimeError(f"telegram_api_error:{str(body)[:300]}")


@dataclass(frozen=True)
class ThreadEventOutboxSnapshot:
    is_running: bool
    inflight_count: int


class ThreadEventOutboxDispatcher:
    def __init__(
        self,
        *,
        runtime,
        claim_batch_size: int = 50,
        max_parallelism: int = 4,
        lease_ttl_sec: int = 30,
        poll_interval_sec: float = 0.3,
        retry_backoff_base_sec: int = 2,
        retry_backoff_max_sec: int = 300,
    ) -> None:
        self._runtime = runtime
        self._storage = runtime.storage
        self._claim_batch_size = max(1, int(claim_batch_size))
        self._max_parallelism = max(1, int(max_parallelism))
        self._lease_ttl_sec = max(1, int(lease_ttl_sec))
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._retry_backoff_base_sec = max(0, int(retry_backoff_base_sec))
        self._retry_backoff_max_sec = max(1, int(retry_backoff_max_sec))
        self._worker_id = f"outbox-{id(self)}"
        self._metrics = self._resolve_metrics_port()
        self._adapters = self._resolve_adapters()
        self._default_adapter = getattr(self._runtime, "thread_event_default_delivery_adapter", None)
        if self._default_adapter is None:
            self._default_adapter = LoggingThreadEventDeliveryAdapter()

        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._inflight_by_delivery: dict[int, asyncio.Task[None]] = {}

    def _resolve_metrics_port(self):
        metrics = getattr(self._runtime, "metrics_port", None)
        if hasattr(metrics, "increment") and hasattr(metrics, "observe_ms"):
            return metrics
        return NoopMetricsPort()

    def _resolve_adapters(self) -> dict[str, Any]:
        raw = getattr(self._runtime, "thread_event_delivery_adapters", None)
        adapters: dict[str, Any] = {}
        if isinstance(raw, dict):
            adapters.update({str(key): value for key, value in raw.items() if key})
        if "telegram" not in adapters:
            token = str(getattr(self._runtime, "telegram_bot_token", "") or "").strip()
            if token:
                adapters["telegram"] = TelegramBotApiDeliveryAdapter(bot_token=token, storage=self._storage)
        return adapters

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="thread-event-outbox-dispatcher")
        logger.info("thread_outbox_dispatcher_started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("thread_outbox_dispatcher_stopped_with_error")
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._dispatch_once()
            except Exception:
                logger.exception("thread_outbox_dispatch_cycle_failed")
            await asyncio.sleep(self._poll_interval_sec)

    async def _dispatch_once(self) -> None:
        with self._storage.transaction(immediate=True):
            claimed = self._storage.claim_pending_event_deliveries(
                limit=self._claim_batch_size,
                lease_owner=self._worker_id,
                lease_ttl_sec=self._lease_ttl_sec,
            )
            dlq_size = int(self._storage.count_event_deliveries(status="failed_dlq"))
        self._metrics.observe_ms("dlq_size", value_ms=float(dlq_size), labels={"operation": "thread_outbox"})
        if not claimed:
            return
        semaphore = asyncio.Semaphore(self._max_parallelism)
        tasks = [asyncio.create_task(self._deliver_with_limit(item, semaphore)) for item in claimed]
        for item, task in zip(claimed, tasks):
            self._inflight_by_delivery[int(item.delivery_id)] = task
        await asyncio.gather(*tasks, return_exceptions=True)
        for item in claimed:
            self._inflight_by_delivery.pop(int(item.delivery_id), None)

    async def _deliver_with_limit(self, delivery: EventDelivery, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            await self._deliver_one(delivery)

    async def _deliver_one(self, delivery: EventDelivery) -> None:
        corr_id = ensure_correlation_id(f"evt-{delivery.event_id}")
        event = self._storage.get_thread_event(str(delivery.event_id))
        if event is None:
            with self._storage.transaction(immediate=True):
                self._storage.mark_event_delivery_dlq(
                    int(delivery.delivery_id),
                    error_code="event_not_found",
                    error_message=f"Thread event not found: {delivery.event_id}",
                )
            return
        adapter = self._resolve_adapter(str(delivery.interface_type))
        idempotency_key = str(delivery.idempotency_key or f"delivery:{delivery.delivery_id}")
        started = monotonic()
        try:
            with correlation_scope(corr_id):
                logger.info(
                    "thread_outbox_delivery_started correlation_id=%s delivery_id=%s event_id=%s interface=%s target=%s",
                    corr_id,
                    delivery.delivery_id,
                    delivery.event_id,
                    delivery.interface_type,
                    delivery.target_id,
                )
                await self._invoke_adapter(adapter, event=event, delivery=delivery, idempotency_key=idempotency_key)
            with self._storage.transaction(immediate=True):
                self._storage.mark_event_delivery_delivered(int(delivery.delivery_id))
            lag_ms = self._delivery_lag_ms(delivery)
            if lag_ms is not None:
                self._metrics.observe_ms(
                    "delivery_lag_ms",
                    value_ms=float(lag_ms),
                    labels={"operation": "thread_outbox", "result": "delivered"},
                )
            self._metrics.increment("deliveries_ok", labels={"operation": "thread_outbox", "result": "ok"})
            self._metrics.increment(
                "thread_outbox_delivery_total",
                labels={"result": "delivered", "interface_type": str(delivery.interface_type), "error_code": ""},
            )
            logger.info(
                "thread_outbox_delivery_done correlation_id=%s delivery_id=%s event_id=%s status=delivered",
                corr_id,
                delivery.delivery_id,
                delivery.event_id,
            )
        except Exception as exc:
            message = str(exc or "")
            code = "delivery_failed"
            self._metrics.increment(
                "deliveries_failed",
                labels={"operation": "thread_outbox", "result": "failed", "error_code": code},
            )
            with self._storage.transaction(immediate=True):
                latest = self._storage.get_event_delivery(int(delivery.delivery_id))
                if latest is None:
                    return
                next_attempt = int(latest.attempt_count) + 1
                if next_attempt >= int(latest.max_attempts):
                    self._storage.mark_event_delivery_dlq(
                        int(delivery.delivery_id),
                        error_code=code,
                        error_message=message or "Delivery failed",
                    )
                    self._metrics.increment(
                        "thread_outbox_delivery_total",
                        labels={
                            "result": "dlq",
                            "interface_type": str(delivery.interface_type),
                            "error_code": code,
                        },
                    )
                    dlq_size = int(self._storage.count_event_deliveries(status="failed_dlq"))
                    self._metrics.observe_ms("dlq_size", value_ms=float(dlq_size), labels={"operation": "thread_outbox"})
                else:
                    delay_sec = self._compute_retry_backoff_sec(next_attempt)
                    self._storage.mark_event_delivery_retry(
                        int(delivery.delivery_id),
                        error_code=code,
                        error_message=message or "Delivery failed",
                        retry_delay_sec=delay_sec,
                    )
                    self._metrics.increment(
                        "thread_outbox_delivery_total",
                        labels={
                            "result": "retry_scheduled",
                            "interface_type": str(delivery.interface_type),
                            "error_code": code,
                        },
                    )
            logger.warning(
                "thread_outbox_delivery_failed correlation_id=%s interface=%s target=%s event_id=%s error=%s",
                corr_id,
                delivery.interface_type,
                delivery.target_id,
                delivery.event_id,
                message,
            )
        finally:
            self._metrics.observe_ms(
                "thread_outbox_delivery_latency_ms",
                value_ms=max(0.0, (monotonic() - started) * 1000.0),
                labels={"interface_type": str(delivery.interface_type)},
            )

    @staticmethod
    def _delivery_lag_ms(delivery: EventDelivery) -> float | None:
        created = str(delivery.created_at or "").strip()
        if not created:
            return None
        try:
            start = datetime.fromisoformat(created)
        except Exception:
            return None
        now = datetime.now(timezone.utc)
        return max(0.0, (now - start).total_seconds() * 1000.0)

    def _resolve_adapter(self, interface_type: str):
        direct = self._adapters.get(interface_type)
        if direct is not None:
            return direct
        wildcard = self._adapters.get("*")
        if wildcard is not None:
            return wildcard
        return self._default_adapter

    @staticmethod
    async def _invoke_adapter(adapter, *, event: ThreadEvent, delivery: EventDelivery, idempotency_key: str) -> None:
        deliver = getattr(adapter, "deliver", None)
        if callable(deliver):
            result = deliver(event=event, delivery=delivery, idempotency_key=idempotency_key)
        elif callable(adapter):
            result = adapter(event=event, delivery=delivery, idempotency_key=idempotency_key)
        else:
            raise RuntimeError("delivery_adapter_invalid")
        if asyncio.iscoroutine(result):
            await result

    def _compute_retry_backoff_sec(self, next_attempt: int) -> int:
        # Exponential backoff: 2, 4, 8, ... capped.
        power = max(0, int(next_attempt) - 1)
        delay = int(self._retry_backoff_base_sec * (2**power))
        return min(delay, self._retry_backoff_max_sec)

    def snapshot(self) -> ThreadEventOutboxSnapshot:
        return ThreadEventOutboxSnapshot(
            is_running=bool(self.is_running),
            inflight_count=int(len(self._inflight_by_delivery)),
        )


def build_thread_event_outbox_dispatcher(runtime) -> ThreadEventOutboxDispatcher | None:
    if runtime is None or getattr(runtime, "storage", None) is None:
        return None
    dispatch_mode = str(getattr(runtime, "dispatch_mode", "single-instance"))
    dispatch_is_runner = bool(getattr(runtime, "dispatch_is_runner", True))
    if dispatch_mode == "single-runner" and not dispatch_is_runner:
        logger.info("thread_outbox_dispatcher_disabled_non_runner")
        return None
    return ThreadEventOutboxDispatcher(runtime=runtime)


__all__ = [
    "LoggingThreadEventDeliveryAdapter",
    "TelegramBotApiDeliveryAdapter",
    "ThreadEventDeliveryAdapter",
    "ThreadEventOutboxDispatcher",
    "build_thread_event_outbox_dispatcher",
]
