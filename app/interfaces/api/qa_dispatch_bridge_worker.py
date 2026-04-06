from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from types import SimpleNamespace
from typing import Awaitable, Callable
from uuid import uuid4

from app.application.contracts import ErrorCode, NoopMetricsPort
from app.application.contracts.runtime_ops import RuntimeOperation
from app.application.observability import correlation_scope, ensure_correlation_id
from app.application.use_cases.qa_dispatch_bridge import (
    claim_questions_for_dispatch_result,
    finalize_question_dispatch_attempt_failure_result,
    persist_question_terminal_outcome_result,
    start_question_dispatch_attempt_result,
    sweep_expired_question_dispatch_leases_result,
)
from app.models import QaQuestion

logger = logging.getLogger("api.qa_dispatch_bridge")


@dataclass(frozen=True)
class BridgeExecutionResult:
    answer_text: str
    role_name: str | None
    answer_team_role_id: int | None
    append_orchestrator_feed: bool = True


class _NoopBot:
    async def send_message(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return None


class _BridgeApp:
    def __init__(self, runtime) -> None:
        if hasattr(runtime, "to_bot_data"):
            bot_data = runtime.to_bot_data()
        else:
            bot_data = {"runtime": runtime}
        self.bot_data = bot_data


async def _default_execute_question(runtime, question: QaQuestion, correlation_id: str) -> BridgeExecutionResult:
    # Lazy import keeps API schema/tests loadable even when Telegram deps are missing.
    from app.services.role_pipeline import execute_role_request

    storage = runtime.storage
    if question.target_team_role_id is None:
        raise RuntimeError("dispatch_rejected:missing_target_team_role_id")
    identity = storage.resolve_team_role_identity(int(question.target_team_role_id))
    if identity is None:
        raise ValueError(f"Team role not found: team_role_id={question.target_team_role_id}")
    team_id, role_id = identity
    role = storage.get_role_by_id(int(role_id))

    execution_user_id, session_token = _resolve_execution_session(
        runtime=runtime,
        question=question,
        team_id=int(team_id),
        role=role,
        correlation_id=correlation_id,
    )

    context = SimpleNamespace(
        application=_BridgeApp(runtime),
        bot=_NoopBot(),
        correlation_id=correlation_id,
    )
    result = await execute_role_request(
        context=context,
        team_id=int(team_id),
        user_id=int(execution_user_id),
        role=role,
        session_token=session_token,
        user_text=str(question.text),
        reply_text=None,
        actor_username=f"api_user_{execution_user_id}",
        trigger_type="api_question",
        mentioned_roles=[role.public_name()],
        recipient=role.public_name(),
        wait_until_available=True,
        queue_request_id=question.question_id,
        correlation_id=correlation_id,
        operation=RuntimeOperation.RUN_CHAIN.value,
    )
    if bool(result.busy_acquired) and result.team_role_id is not None:
        try:
            runtime.role_runtime_status_service.release_busy(
                team_role_id=int(result.team_role_id),
                release_reason="api_bridge_answered",
            )
        except Exception:
            logger.exception(
                "qa_bridge_release_busy_failed correlation_id=%s question_id=%s team_role_id=%s",
                correlation_id,
                question.question_id,
                result.team_role_id,
            )

    return BridgeExecutionResult(
        answer_text=str(result.response_text),
        role_name=role.public_name(),
        answer_team_role_id=int(result.team_role_id or question.target_team_role_id),
        append_orchestrator_feed=True,
    )


def _resolve_role_requires_auth(*, runtime, team_id: int, role, correlation_id: str | None = None) -> bool:
    # Keep provider/model resolution aligned with runtime path used in Telegram flow.
    from app.services.prompt_builder import resolve_provider_model, role_requires_auth

    provider_registry = dict(getattr(runtime, "provider_registry", {}) or {})
    provider_models = list(getattr(runtime, "provider_models", []) or [])
    provider_model_map = dict(getattr(runtime, "provider_model_map", {}) or {})
    default_provider_id = str(getattr(runtime, "default_provider_id", "") or "")
    storage = runtime.storage
    try:
        group_role = storage.get_team_role(int(team_id), int(role.role_id))
        selected_model = group_role.model_override or getattr(role, "llm_model", None)
        if provider_models:
            model_override = resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                selected_model,
            )
        else:
            model_override = selected_model
        return bool(role_requires_auth(provider_registry, model_override, default_provider_id))
    except Exception:
        # Fail-safe: deny-by-default when provider config is unavailable/invalid.
        logger.warning(
            "qa_bridge_auth_mode_resolution_failed correlation_id=%s team_id=%s role_id=%s",
            ensure_correlation_id(correlation_id),
            team_id,
            int(getattr(role, "role_id", 0) or 0),
        )
        return True


def _resolve_execution_auth_token(runtime, question: QaQuestion, correlation_id: str):
    storage = runtime.storage
    question_user_id = int(question.created_by_user_id)
    token = storage.get_auth_token(question_user_id)
    if token is not None and bool(token.is_authorized):
        return question_user_id, token

    owner_user_id = getattr(runtime, "owner_user_id", None)
    if owner_user_id is not None:
        owner_id = int(owner_user_id)
        if owner_id != question_user_id:
            fallback = storage.get_auth_token(owner_id)
            if fallback is not None and bool(fallback.is_authorized):
                logger.warning(
                    "qa_bridge_token_owner_fallback correlation_id=%s question_id=%s question_user_id=%s owner_user_id=%s",
                    correlation_id,
                    question.question_id,
                    question_user_id,
                    owner_id,
                )
                return owner_id, fallback

    raise RuntimeError("dispatch_rejected:missing_authorized_token")


def _resolve_execution_session(*, runtime, question: QaQuestion, team_id: int, role, correlation_id: str) -> tuple[int, str]:
    requires_auth = _resolve_role_requires_auth(
        runtime=runtime,
        team_id=team_id,
        role=role,
        correlation_id=correlation_id,
    )
    question_user_id = int(question.created_by_user_id)
    if not requires_auth:
        logger.info(
            "qa_bridge_auth_mode_none correlation_id=%s question_id=%s team_id=%s team_role_id=%s execution_user_id=%s",
            correlation_id,
            question.question_id,
            team_id,
            question.target_team_role_id,
            question_user_id,
        )
        return question_user_id, ""
    execution_user_id, auth_token = _resolve_execution_auth_token(runtime, question, correlation_id)
    return execution_user_id, runtime.cipher.decrypt(auth_token.encrypted_token)


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
                    self._metrics.increment(
                        "runtime_inflight_operations",
                        labels={"operation": "qa_dispatch_bridge"},
                        value=-1,
                    )

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


def _map_execution_failure(exc: Exception) -> tuple[str, str]:
    text = str(exc or "")
    lowered = text.lower()
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
