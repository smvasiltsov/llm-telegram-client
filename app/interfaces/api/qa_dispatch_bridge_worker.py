from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
import hashlib
import json
from time import monotonic
from typing import Awaitable, Callable, Literal
from uuid import uuid4

from app.application.contracts import ErrorCode, NoopMetricsPort
from app.application.observability import correlation_scope, ensure_correlation_id
from app.application.use_cases.qa_api import QaCreateQuestionRequest, create_question_result
from app.application.use_cases.qa_dispatch_bridge import (
    claim_questions_for_dispatch_result,
    finalize_question_dispatch_attempt_failure_result,
    persist_question_terminal_outcome_result,
    start_question_dispatch_attempt_result,
    sweep_expired_question_dispatch_leases_result,
)
from app.application.use_cases.qa_runtime_bridge_core import (
    BridgeExecutionResult,
    execute_question_through_adapter,
    resolve_execution_auth_token as _core_resolve_execution_auth_token,
    resolve_execution_session as _core_resolve_execution_session,
    resolve_role_requires_auth as _core_resolve_role_requires_auth,
)
from app.interfaces.runtime.qa_runtime_execution_adapter import TelegramQaRuntimeExecutionAdapter
from app.models import QaQuestion
from app.utils import extract_role_mentions

logger = logging.getLogger("api.qa_dispatch_bridge")


_DEFAULT_RUNTIME_EXECUTION_ADAPTER = TelegramQaRuntimeExecutionAdapter()


@dataclass(frozen=True)
class QaPostAnswerDispatchItem:
    target_team_role_id: int
    text: str
    reason: Literal["mention_tag", "orchestrator_user_event", "orchestrator_answer_event"]
    origin_type: Literal["role_dispatch", "orchestrator"]
    parent_question_id: str
    parent_answer_id: str


@dataclass(frozen=True)
class QaPostAnswerDispatchPlan:
    items: tuple[QaPostAnswerDispatchItem, ...]


async def _default_execute_question(runtime, question: QaQuestion, correlation_id: str) -> BridgeExecutionResult:
    return await execute_question_through_adapter(
        runtime=runtime,
        question=question,
        correlation_id=correlation_id,
        adapter=_DEFAULT_RUNTIME_EXECUTION_ADAPTER,
    )


def _resolve_role_requires_auth(*, runtime, team_id: int, role, correlation_id: str | None = None) -> bool:
    return _core_resolve_role_requires_auth(
        runtime=runtime,
        team_id=team_id,
        role=role,
        correlation_id=correlation_id,
    )


def _resolve_execution_auth_token(runtime, question: QaQuestion, correlation_id: str):
    return _core_resolve_execution_auth_token(runtime, question, correlation_id)


def _resolve_execution_session(*, runtime, question: QaQuestion, team_id: int, role, correlation_id: str) -> tuple[int, str]:
    return _core_resolve_execution_session(
        runtime=runtime,
        question=question,
        team_id=team_id,
        role=role,
        correlation_id=correlation_id,
    )


class QaDispatchBridgeWorker:
    def __init__(
        self,
        *,
        runtime,
        claim_batch_size: int = 20,
        max_parallelism: int = 4,
        lease_ttl_sec: int = 120,
        max_attempts: int = 3,
        retry_delay_sec: int = 0,
        sweep_interval_sec: float = 1.0,
        execute_question_fn: Callable[[object, QaQuestion, str], Awaitable[BridgeExecutionResult]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._storage = runtime.storage
        self._claim_batch_size = max(1, int(claim_batch_size))
        self._max_parallelism = max(1, int(max_parallelism))
        self._lease_ttl_sec = max(1, int(lease_ttl_sec))
        self._max_attempts = max(1, int(max_attempts))
        self._retry_delay_sec = max(0, int(retry_delay_sec))
        self._sweep_interval_sec = max(0.1, float(sweep_interval_sec))
        self._lease_heartbeat_sec = max(0.2, min(self._sweep_interval_sec, float(self._lease_ttl_sec) / 3.0))
        self._execute_question = execute_question_fn or _default_execute_question

        self._metrics = self._resolve_metrics_port()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._pending_ids: asyncio.Queue[str] = asyncio.Queue()
        self._queued_ids: set[str] = set()
        self._inflight_by_question: dict[str, asyncio.Task[None]] = {}
        self._role_locks: dict[int, asyncio.Lock] = {}

    def _resolve_metrics_port(self):
        metrics = getattr(self._runtime, "metrics_port", None)
        if hasattr(metrics, "increment") and hasattr(metrics, "observe_ms"):
            return metrics
        return NoopMetricsPort()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop(), name="qa-dispatch-bridge")
        logger.info("qa_bridge_started")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("qa_bridge_stopped_with_error")
        self._task = None
        self._loop = None

    def enqueue_question(self, question_id: str) -> None:
        qid = str(question_id or "").strip()
        if not qid:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(self._enqueue_in_loop, qid)

    def _enqueue_in_loop(self, question_id: str) -> None:
        if question_id in self._queued_ids or question_id in self._inflight_by_question:
            return
        self._queued_ids.add(question_id)
        self._pending_ids.put_nowait(question_id)
        self._wake.set()

    def _role_lock(self, team_role_id: int | None) -> asyncio.Lock:
        key = int(team_role_id or 0)
        lock = self._role_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._role_locks[key] = lock
        return lock

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self._poll_and_recover()
            self._schedule_pending()
            self._emit_queue_depth_metric()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._sweep_interval_sec)
            except TimeoutError:
                pass
            self._wake.clear()

    async def _poll_and_recover(self) -> None:
        sweep = sweep_expired_question_dispatch_leases_result(
            self._storage,
            max_attempts=self._max_attempts,
            attempt_ttl_sec=self._lease_ttl_sec,
        )
        if sweep.is_ok and sweep.value is not None:
            for item in sweep.value.requeued:
                logger.info(
                    "qa_bridge_sweep_requeued question_id=%s team_id=%s team_role_id=%s attempt=%s",
                    item.question_id,
                    item.team_id,
                    item.target_team_role_id,
                    self._storage.get_qa_dispatch_attempt_count(item.question_id),
                )
                self._enqueue_in_loop(item.question_id)
            for item in sweep.value.timed_out:
                logger.warning(
                    "qa_bridge_sweep_timed_out question_id=%s team_id=%s team_role_id=%s attempt=%s error_code=%s",
                    item.question_id,
                    item.team_id,
                    item.target_team_role_id,
                    self._storage.get_qa_dispatch_attempt_count(item.question_id),
                    item.error_code,
                )
                self._emit_terminal_metric(status=item.status, error_code=item.error_code)

        claimed = claim_questions_for_dispatch_result(
            self._storage,
            limit=self._claim_batch_size,
            max_attempts=self._max_attempts,
        )
        if claimed.is_ok and claimed.value is not None:
            for item in claimed.value:
                self._enqueue_in_loop(item.question_id)

        for item in self._storage.list_queued_questions_for_dispatch(
            limit=self._claim_batch_size,
            max_attempts=self._max_attempts,
        ):
            self._enqueue_in_loop(item.question_id)

    def _schedule_pending(self) -> None:
        while len(self._inflight_by_question) < self._max_parallelism and not self._pending_ids.empty():
            question_id = self._pending_ids.get_nowait()
            self._queued_ids.discard(question_id)
            if question_id in self._inflight_by_question:
                continue
            task = asyncio.create_task(self._process_question(question_id), name=f"qa-dispatch-{question_id}")
            self._inflight_by_question[question_id] = task
            task.add_done_callback(lambda _t, qid=question_id: self._on_task_done(qid))

    def _on_task_done(self, question_id: str) -> None:
        self._inflight_by_question.pop(question_id, None)
        self._wake.set()

    def _build_post_answer_dispatch_plan(
        self,
        *,
        question: QaQuestion,
        answer_id: str,
        answer_text: str,
    ) -> QaPostAnswerDispatchPlan:
        team_id = int(question.team_id)
        source_team_role_id = int(question.target_team_role_id or 0)
        role_items = self._storage.list_roles_for_team(team_id)
        role_map = {item.public_name().strip().lower(): item for item in role_items if item.public_name().strip()}
        mention_names = extract_role_mentions(str(answer_text or ""), set(role_map.keys()))

        planned: list[QaPostAnswerDispatchItem] = []
        max_fanout = max(1, int(getattr(self._runtime, "qa_post_answer_max_fanout", 8) or 8))
        seen_targets: set[int] = set()
        for name in mention_names:
            role = role_map.get(str(name).strip().lower())
            if role is None:
                continue
            team_role_id = self._storage.resolve_team_role_id(team_id, int(role.role_id), ensure_exists=False)
            if team_role_id is None:
                continue
            target_team_role_id = int(team_role_id)
            if target_team_role_id <= 0 or target_team_role_id == source_team_role_id:
                continue
            if target_team_role_id in seen_targets:
                continue
            seen_targets.add(target_team_role_id)
            planned.append(
                QaPostAnswerDispatchItem(
                    target_team_role_id=target_team_role_id,
                    text=str(answer_text or ""),
                    reason="mention_tag",
                    origin_type="role_dispatch",
                    parent_question_id=question.question_id,
                    parent_answer_id=answer_id,
                )
            )
            if len(planned) >= max_fanout:
                break

        orchestrator = self._storage.get_enabled_orchestrator_for_team(team_id)
        if orchestrator is not None:
            orchestrator_team_role_id = int(orchestrator.team_role_id or 0)
            if orchestrator_team_role_id > 0 and orchestrator_team_role_id != source_team_role_id:
                # For direct user -> role flow, orchestrator receives both user input and role answer.
                if str(question.origin_type or "").strip().lower() == "user":
                    planned.append(
                        QaPostAnswerDispatchItem(
                            target_team_role_id=orchestrator_team_role_id,
                            text=str(question.text or ""),
                            reason="orchestrator_user_event",
                            origin_type="orchestrator",
                            parent_question_id=question.question_id,
                            parent_answer_id=answer_id,
                        )
                    )
                planned.append(
                    QaPostAnswerDispatchItem(
                        target_team_role_id=orchestrator_team_role_id,
                        text=str(answer_text or ""),
                        reason="orchestrator_answer_event",
                        origin_type="orchestrator",
                        parent_question_id=question.question_id,
                        parent_answer_id=answer_id,
                    )
                )

        return QaPostAnswerDispatchPlan(items=tuple(planned))

    def _question_lineage_depth(self, question: QaQuestion) -> int:
        depth = 0
        seen: set[str] = set()
        current = question
        while current.source_question_id:
            parent_id = str(current.source_question_id).strip()
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            parent = self._storage.get_question(parent_id)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    def _on_answer_generated(
        self,
        *,
        correlation_id: str,
        question: QaQuestion,
        answer_id: str,
        answer_text: str,
    ) -> QaPostAnswerDispatchPlan:
        plan = self._build_post_answer_dispatch_plan(
            question=question,
            answer_id=answer_id,
            answer_text=answer_text,
        )
        for item in plan.items:
            logger.info(
                "qa_bridge_post_answer_dispatch_planned correlation_id=%s parent_question_id=%s parent_answer_id=%s target_team_role_id=%s reason=%s origin_type=%s",
                correlation_id,
                item.parent_question_id,
                item.parent_answer_id,
                item.target_team_role_id,
                item.reason,
                item.origin_type,
            )
        return plan

    @staticmethod
    def _post_answer_dispatch_idempotency_key(item: QaPostAnswerDispatchItem) -> str:
        text_hash = hashlib.sha256(str(item.text or "").encode("utf-8")).hexdigest()[:24]
        return (
            f"qa-post-answer:{item.reason}:"
            f"{item.parent_question_id}:{item.parent_answer_id}:"
            f"{int(item.target_team_role_id)}:{text_hash}"
        )

    def _dispatch_post_answer_plan(
        self,
        *,
        correlation_id: str,
        parent_question: QaQuestion,
        plan: QaPostAnswerDispatchPlan,
    ) -> None:
        max_hops = max(0, int(getattr(self._runtime, "qa_post_answer_max_hops", 3) or 3))
        depth = self._question_lineage_depth(parent_question)
        if depth >= max_hops:
            logger.info(
                "qa_bridge_post_answer_dispatch_skipped_max_hops correlation_id=%s parent_question_id=%s depth=%s max_hops=%s",
                correlation_id,
                parent_question.question_id,
                depth,
                max_hops,
            )
            return
        origin_interface = self._resolve_origin_interface_for_question(parent_question) or "qa_bridge"
        for item in plan.items:
            if item.reason not in {"mention_tag", "orchestrator_user_event", "orchestrator_answer_event"}:
                continue
            text = str(item.text or "").strip()
            if not text:
                continue
            idempotency_key = self._post_answer_dispatch_idempotency_key(item)
            result = create_question_result(
                self._storage,
                request=QaCreateQuestionRequest(
                    team_id=int(parent_question.team_id),
                    created_by_user_id=int(parent_question.created_by_user_id),
                    text=text,
                    team_role_id=int(item.target_team_role_id),
                    origin_type=item.origin_type,
                    source_question_id=item.parent_question_id,
                    parent_answer_id=item.parent_answer_id,
                    thread_id=parent_question.thread_id,
                    origin_interface=origin_interface,
                ),
                idempotency_key=idempotency_key,
                provider_registry=dict(getattr(self._runtime, "provider_registry", {}) or {}),
                provider_models=list(getattr(self._runtime, "provider_models", []) or []),
                provider_model_map=dict(getattr(self._runtime, "provider_model_map", {}) or {}),
                default_provider_id=str(getattr(self._runtime, "default_provider_id", "") or ""),
                scope="qa.post_answer_dispatch",
                metrics_port=getattr(self._runtime, "metrics_port", None),
            )
            if result.is_error or result.value is None:
                logger.warning(
                    "qa_bridge_post_answer_dispatch_failed correlation_id=%s parent_question_id=%s target_team_role_id=%s reason=%s error_code=%s",
                    correlation_id,
                    item.parent_question_id,
                    item.target_team_role_id,
                    item.reason,
                    (result.error.code if result.error is not None else ErrorCode.INTERNAL_UNEXPECTED.value),
                )
                continue
            child = result.value.question
            logger.info(
                "qa_bridge_post_answer_dispatch_created correlation_id=%s parent_question_id=%s child_question_id=%s target_team_role_id=%s idempotent_replay=%s",
                correlation_id,
                item.parent_question_id,
                child.question_id,
                item.target_team_role_id,
                bool(result.value.idempotent_replay),
            )
            if not bool(result.value.idempotent_replay):
                self.enqueue_question(child.question_id)

    def _resolve_origin_interface_for_question(self, question: QaQuestion) -> str | None:
        events = self._storage.list_thread_events(thread_id=str(question.thread_id), limit=500)
        matched = [
            item
            for item in events
            if str(item.event_type) == "thread.message.created"
            and str(item.direction) == "question"
            and str(item.question_id or "") == str(question.question_id)
        ]
        if not matched:
            return None
        latest = max(matched, key=lambda item: int(item.seq))
        origin = str(latest.origin_interface or "").strip()
        return origin or None

    async def _process_question(self, question_id: str) -> None:
        question = self._storage.get_question(question_id)
        if question is None:
            return
        role_lock = self._role_lock(question.target_team_role_id)
        async with role_lock:
            current = self._storage.get_question(question_id)
            if current is None:
                return
            if current.status == "accepted":
                _ = claim_questions_for_dispatch_result(
                    self._storage,
                    limit=self._claim_batch_size,
                    max_attempts=self._max_attempts,
                )
                current = self._storage.get_question(question_id)
            if current is None or current.status != "queued":
                return

            started = start_question_dispatch_attempt_result(
                self._storage,
                question_id=question_id,
                lease_ttl_sec=self._lease_ttl_sec,
                max_attempts=self._max_attempts,
            )
            if started.is_error or started.value is None:
                return

            corr_id = ensure_correlation_id(f"qa-{question_id}")
            attempt = int(self._storage.get_qa_dispatch_attempt_count(question_id))
            operation_started = monotonic()
            with correlation_scope(corr_id):
                self._metrics.increment(
                    "runtime_operations_total",
                    labels={
                        "operation": "qa_dispatch_bridge",
                        "result": "started",
                        "error_code": "",
                    },
                )
                self._metrics.increment(
                    "runtime_inflight_operations",
                    labels={"operation": "qa_dispatch_bridge"},
                    value=1,
                )
                logger.info(
                    "qa_bridge_dispatch_started correlation_id=%s question_id=%s team_id=%s team_role_id=%s attempt=%s",
                    corr_id,
                    started.value.question_id,
                    started.value.team_id,
                    started.value.target_team_role_id,
                    attempt,
                )
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_attempt(
                        question_id=started.value.question_id,
                        stop_event=heartbeat_stop,
                    ),
                    name=f"qa-dispatch-heartbeat-{started.value.question_id}",
                )
                try:
                    execution = await self._execute_question(self._runtime, started.value, corr_id)
                    outcome = persist_question_terminal_outcome_result(
                        self._storage,
                        question_id=started.value.question_id,
                        status="answered",
                        answer_id=str(uuid4()),
                        answer_text=execution.answer_text,
                        answer_team_role_id=execution.answer_team_role_id,
                        answer_role_name=execution.role_name,
                        append_orchestrator_feed=bool(execution.append_orchestrator_feed),
                    )
                    if outcome.is_error or outcome.value is None or outcome.value.question is None:
                        raise RuntimeError("internal_execution_error:persist_terminal_outcome_failed")
                    final_q = outcome.value.question
                    if outcome.value.answer is not None:
                        answer_origin_interface = self._resolve_origin_interface_for_question(final_q) or "qa_bridge"
                        answer_event_payload = json.dumps(
                            {
                                "kind": "role-answer",
                                "text": str(outcome.value.answer.text or ""),
                                "lineage": {
                                    "source_question_id": final_q.source_question_id,
                                    "parent_answer_id": final_q.parent_answer_id,
                                },
                            },
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        with self._storage.transaction(immediate=True):
                            answer_event = self._storage.create_thread_event(
                                team_id=int(final_q.team_id),
                                thread_id=str(final_q.thread_id),
                                event_type="thread.message.created",
                                author_type="role",
                                direction="answer",
                                origin_interface=answer_origin_interface,
                                source_ref_type="answer",
                                source_ref_id=str(outcome.value.answer.answer_id),
                                question_id=str(final_q.question_id),
                                answer_id=str(outcome.value.answer.answer_id),
                                source_question_id=final_q.source_question_id,
                                parent_answer_id=final_q.parent_answer_id,
                                payload_json=answer_event_payload,
                                idempotency_key=f"thread-message:answer:{outcome.value.answer.answer_id}",
                            )
                        self._metrics.increment(
                            "events_published",
                            labels={"operation": "thread_event_publish", "result": "ok", "error_code": ""},
                        )
                        logger.info(
                            "thread_event_published correlation_id=%s event_id=%s thread_id=%s seq=%s answer_id=%s kind=role-answer",
                            corr_id,
                            answer_event.event_id,
                            answer_event.thread_id,
                            answer_event.seq,
                            outcome.value.answer.answer_id,
                        )
                    latency_ms = max(0.0, (monotonic() - operation_started) * 1000.0)
                    self._metrics.observe_ms(
                        "runtime_transition_latency_ms",
                        value_ms=latency_ms,
                        labels={"operation": "qa_dispatch_bridge", "status": str(final_q.status)},
                    )
                    self._emit_terminal_metric(status=final_q.status, error_code=final_q.error_code)
                    logger.info(
                        "qa_bridge_dispatch_answered correlation_id=%s question_id=%s team_id=%s team_role_id=%s attempt=%s answer_id=%s",
                        corr_id,
                        final_q.question_id,
                        final_q.team_id,
                        final_q.target_team_role_id,
                        attempt,
                        (outcome.value.answer.answer_id if outcome.value.answer is not None else ""),
                    )
                    dispatch_plan = self._on_answer_generated(
                        correlation_id=corr_id,
                        question=final_q,
                        answer_id=(outcome.value.answer.answer_id if outcome.value.answer is not None else ""),
                        answer_text=str(execution.answer_text or ""),
                    )
                    self._dispatch_post_answer_plan(
                        correlation_id=corr_id,
                        parent_question=final_q,
                        plan=dispatch_plan,
                    )
                except Exception as exc:
                    error_code, message = _map_execution_failure(exc)
                    finalized = finalize_question_dispatch_attempt_failure_result(
                        self._storage,
                        question_id=started.value.question_id,
                        error_code=error_code,
                        error_message=message,
                        max_attempts=self._max_attempts,
                        retry_delay_sec=self._retry_delay_sec,
                    )
                    status = finalized.value.status if finalized.is_ok and finalized.value is not None else "failed"
                    self._emit_terminal_metric(status=status, error_code=error_code)
                    if status == "queued":
                        self._metrics.increment(
                            "runtime_operations_total",
                            labels={
                                "operation": "qa_dispatch_bridge",
                                "result": "retry",
                                "error_code": str(error_code or ""),
                            },
                        )
                        logger.warning(
                            "qa_bridge_dispatch_retry correlation_id=%s question_id=%s team_id=%s team_role_id=%s attempt=%s error_code=%s",
                            corr_id,
                            started.value.question_id,
                            started.value.team_id,
                            started.value.target_team_role_id,
                            attempt,
                            error_code,
                        )
                    logger.exception(
                        "qa_bridge_dispatch_failed correlation_id=%s question_id=%s team_id=%s team_role_id=%s attempt=%s error_code=%s",
                        corr_id,
                        started.value.question_id,
                        started.value.team_id,
                        started.value.target_team_role_id,
                        attempt,
                        error_code,
                    )
                finally:
                    heartbeat_stop.set()
                    try:
                        await heartbeat_task
                    except Exception:
                        logger.exception("qa_bridge_heartbeat_stopped_with_error question_id=%s", started.value.question_id)
                    self._metrics.increment(
                        "runtime_inflight_operations",
                        labels={"operation": "qa_dispatch_bridge"},
                        value=-1,
                    )

    async def _heartbeat_attempt(self, *, question_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._lease_heartbeat_sec)
                continue
            except TimeoutError:
                pass
            try:
                with self._storage.transaction(immediate=True):
                    alive = self._storage.heartbeat_question_dispatch_attempt(
                        question_id=question_id,
                        lease_ttl_sec=self._lease_ttl_sec,
                    )
            except Exception:
                logger.exception("qa_bridge_heartbeat_failed question_id=%s", question_id)
                continue
            if not alive:
                logger.warning("qa_bridge_heartbeat_stale_or_lost question_id=%s", question_id)
                return

    def _emit_terminal_metric(self, *, status: str, error_code: str | None) -> None:
        self._metrics.increment(
            "runtime_operations_total",
            labels={
                "operation": "qa_dispatch_bridge",
                "result": str(status),
                "error_code": str(error_code or ""),
            },
        )

    def _emit_queue_depth_metric(self) -> None:
        self._metrics.observe_ms(
            "runtime_queue_depth",
            value_ms=float(max(0, self._pending_ids.qsize())),
            labels={"queue_name": "qa_dispatch_bridge"},
        )

    def snapshot(self) -> dict[str, int | bool]:
        return {
            "is_running": bool(self.is_running),
            "pending_queue_depth": int(self._pending_ids.qsize()),
            "inflight_count": int(len(self._inflight_by_question)),
            "queued_ids_count": int(len(self._queued_ids)),
        }


def _map_execution_failure(exc: Exception) -> tuple[str, str]:
    text = str(exc or "")
    lowered = text.lower()
    if "execution attempt lease expired" in lowered or "lease expired" in lowered:
        return "runtime_dispatch_timeout", text or "Dispatch lease expired"
    if "dispatch_rejected" in lowered:
        return "dispatch_rejected", text or "Dispatch rejected"
    if "runtime_busy_conflict" in lowered or "busy_conflict" in lowered:
        return "runtime_busy_conflict", text or "Runtime busy conflict"
    timeout_types = (asyncio.TimeoutError, TimeoutError)
    if isinstance(exc, timeout_types) or "timeout" in lowered:
        return "provider_timeout", text or "Provider timeout"
    if "provider" in lowered or "http" in lowered:
        return "provider_error", text or "Provider error"
    if isinstance(exc, ValueError) and ("not found" in lowered or "invalid" in lowered):
        return "dispatch_rejected", text or "Dispatch rejected"
    return "internal_execution_error", text or "Internal execution error"


def build_dispatch_bridge_worker(runtime) -> QaDispatchBridgeWorker | None:
    if runtime is None or getattr(runtime, "storage", None) is None:
        return None
    dispatch_mode = str(getattr(runtime, "dispatch_mode", "single-instance"))
    dispatch_is_runner = bool(getattr(runtime, "dispatch_is_runner", True))
    if dispatch_mode == "single-runner" and not dispatch_is_runner:
        logger.info("qa_bridge_disabled_non_runner")
        return None
    required = (
        "storage",
        "cipher",
        "llm_executor",
        "session_resolver",
        "role_runtime_status_service",
    )
    for attr in required:
        if getattr(runtime, attr, None) is None:
            logger.info("qa_bridge_disabled_missing_runtime_dependency dependency=%s", attr)
            return None
    execute_override = getattr(runtime, "qa_dispatch_bridge_execute_question_fn", None)
    if callable(execute_override):
        return QaDispatchBridgeWorker(runtime=runtime, execute_question_fn=execute_override)
    return QaDispatchBridgeWorker(runtime=runtime)


__all__ = [
    "BridgeExecutionResult",
    "QaDispatchBridgeWorker",
    "build_dispatch_bridge_worker",
]
