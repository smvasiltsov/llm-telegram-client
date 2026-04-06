from __future__ import annotations

import logging
from uuid import uuid4
from typing import Any, Callable, Awaitable

from app.application.contracts import ErrorCode, NoopMetricsPort, Result, build_operation_labels
from app.application.observability import ensure_correlation_id
from app.application.contracts.runtime_ops import (
    RuntimeOperation,
    RuntimeOperationResult,
    RuntimeState,
    RuntimeTransition,
)
from app.services.role_dispatch_queue import DispatchPolicyRejectedError

logger = logging.getLogger("runtime.operation")


RUNTIME_OPERATION_TRANSITION_TABLE: tuple[dict[str, str], ...] = (
    {
        "operation": RuntimeOperation.RUN_CHAIN.value,
        "trigger": "group",
        "path": f"{RuntimeState.QUEUED.value}->{RuntimeState.BUSY.value}->{RuntimeState.FREE.value}",
        "on_error": f"{RuntimeState.BUSY.value}->{RuntimeState.PENDING.value}",
    },
    {
        "operation": RuntimeOperation.DISPATCH_MENTIONS.value,
        "trigger": "group",
        "path": f"{RuntimeState.QUEUED.value}->{RuntimeState.BUSY.value}->{RuntimeState.FREE.value}",
        "on_error": f"{RuntimeState.BUSY.value}->{RuntimeState.PENDING.value}",
    },
    {
        "operation": RuntimeOperation.ORCHESTRATOR_POST_EVENT.value,
        "trigger": "group",
        "path": f"{RuntimeState.QUEUED.value}->{RuntimeState.BUSY.value}->{RuntimeState.FREE.value}",
        "on_error": f"{RuntimeState.BUSY.value}->{RuntimeState.PENDING.value}",
    },
    {
        "operation": RuntimeOperation.PENDING_REPLAY.value,
        "trigger": "pending",
        "path": f"{RuntimeState.QUEUED.value}->{RuntimeState.BUSY.value}->{RuntimeState.FREE.value}",
        "on_error": f"{RuntimeState.BUSY.value}->{RuntimeState.PENDING.value}",
    },
)


def _resolve_metrics_port(context: Any):
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", None)
    if isinstance(bot_data, dict):
        direct = bot_data.get("metrics_port")
        if hasattr(direct, "increment") and hasattr(direct, "observe_ms") and hasattr(direct, "operation_timer"):
            return direct
        runtime = bot_data.get("runtime")
        runtime_metrics = getattr(runtime, "metrics_port", None)
        if (
            hasattr(runtime_metrics, "increment")
            and hasattr(runtime_metrics, "observe_ms")
            and hasattr(runtime_metrics, "operation_timer")
        ):
            return runtime_metrics
    return NoopMetricsPort()


def _resolve_dispatch_runtime_labels(context: Any) -> tuple[str, str]:
    app = getattr(context, "application", None)
    bot_data = getattr(app, "bot_data", None)
    if isinstance(bot_data, dict):
        runtime = bot_data.get("runtime")
        mode = str(getattr(runtime, "dispatch_mode", "single-instance"))
        runner = "runner" if bool(getattr(runtime, "dispatch_is_runner", True)) else "non-runner"
        return mode, runner
    return "single-instance", "runner"


def _build_runtime_transitions(
    *,
    operation: str,
    trigger: str,
    request_id: str,
    completed: bool,
    pending_saved: bool,
    replay_scheduled: bool,
) -> tuple[RuntimeTransition, ...]:
    transitions: list[RuntimeTransition] = [
        RuntimeTransition(
            operation=operation,
            trigger=trigger,
            from_state=RuntimeState.QUEUED.value,
            to_state=RuntimeState.BUSY.value,
            team_role_id=None,
            request_id=request_id,
            reason="slot_granted",
        )
    ]
    if completed:
        transitions.append(
            RuntimeTransition(
                operation=operation,
                trigger=trigger,
                from_state=RuntimeState.BUSY.value,
                to_state=RuntimeState.FREE.value,
                team_role_id=None,
                request_id=request_id,
                reason="response_sent",
            )
        )
        return tuple(transitions)
    reason = "delivery_failed"
    if replay_scheduled:
        reason = "replay_failed"
    elif pending_saved:
        reason = "unauthorized_pending_saved"
    transitions.append(
        RuntimeTransition(
            operation=operation,
            trigger=trigger,
            from_state=RuntimeState.BUSY.value,
            to_state=RuntimeState.PENDING.value,
            team_role_id=None,
            request_id=request_id,
            reason=reason,
        )
    )
    return tuple(transitions)


async def execute_run_chain_operation(
    *,
    context,
    team_id: int,
    chat_id: int,
    user_id: int,
    session_token: str,
    roles: list,
    user_text: str,
    reply_text: str | None,
    actor_username: str | None,
    reply_to_message_id: int,
    is_all: bool,
    apply_plugins: bool,
    save_pending_on_unauthorized: bool,
    pending_role_name: str | None = None,
    allow_orchestrator_post_event: bool = True,
    trigger_type_orchestrator: str = "orchestrator_all_messages",
    chain_origin: str = "group",
    operation: str | RuntimeOperation = RuntimeOperation.RUN_CHAIN,
    request_id: str | None = None,
    correlation_id: str | None = None,
    run_chain_fn: Callable[..., Awaitable[Any]] | None = None,
) -> Result[RuntimeOperationResult]:
    # Lazy import keeps use-case tests independent from Telegram runtime deps.
    if run_chain_fn is None:
        from app.services.role_pipeline import run_chain as run_chain_fn

    op_name = operation.value if isinstance(operation, RuntimeOperation) else str(operation)
    req_id = request_id or uuid4().hex
    corr_id = ensure_correlation_id(correlation_id)
    metrics = _resolve_metrics_port(context)
    dispatch_mode, dispatch_runner = _resolve_dispatch_runtime_labels(context)
    timer = metrics.operation_timer(op_name, transport="telegram")
    metrics.increment(
        "runtime_inflight_operations",
        labels={"operation": op_name},
        value=1,
    )
    logger.info(
        "runtime_operation_started correlation_id=%s operation=%s request_id=%s trigger=%s team_id=%s user_id=%s",
        corr_id,
        op_name,
        req_id,
        chain_origin,
        team_id,
        user_id,
    )
    metrics.increment(
        "runtime_operation_total",
        labels=build_operation_labels(
            operation=op_name,
            transport="telegram",
            result="started",
            mode=dispatch_mode,
            runner=dispatch_runner,
        ),
    )
    if op_name == RuntimeOperation.PENDING_REPLAY.value:
        metrics.increment(
            "runtime_pending_replay_total",
            labels=build_operation_labels(
                operation=op_name,
                transport="telegram",
                result="started",
                mode=dispatch_mode,
                runner=dispatch_runner,
            ),
        )
    try:
        chain_result = await run_chain_fn(
            context=context,
            team_id=team_id,
            chat_id=chat_id,
            user_id=user_id,
            session_token=session_token,
            roles=roles,
            user_text=user_text,
            reply_text=reply_text,
            actor_username=actor_username,
            reply_to_message_id=reply_to_message_id,
            is_all=is_all,
            apply_plugins=apply_plugins,
            save_pending_on_unauthorized=save_pending_on_unauthorized,
            pending_role_name=pending_role_name,
            allow_orchestrator_post_event=allow_orchestrator_post_event,
            trigger_type_orchestrator=trigger_type_orchestrator,
            chain_origin=chain_origin,  # type: ignore[arg-type]
            correlation_id=corr_id,
        )
    except DispatchPolicyRejectedError as exc:
        reject_code = (
            ErrorCode.RUNTIME_NON_RUNNER_REJECT
            if str(exc.reason or "").strip().lower() == "non_runner_instance"
            else ErrorCode.RUNTIME_BUSY_CONFLICT
        )
        failure = Result.fail(
            reject_code,
            "Runtime dispatch unavailable on non-runner instance",
            details={
                "entity": "runtime_operation",
                "operation": op_name,
                "cause": "dispatch_policy_rejected",
                "request_id": req_id,
                "correlation_id": corr_id,
                "mode": exc.mode,
                "runner": exc.is_runner,
                "reason": exc.reason,
            },
        )
        error_code = failure.error.code if failure.error else reject_code.value
        metrics.increment(
            "runtime_operation_total",
            labels=build_operation_labels(
                operation=op_name,
                transport="telegram",
                result="failed",
                error_code=error_code,
                mode=dispatch_mode,
                runner=dispatch_runner,
            ),
        )
        timer.observe(result="failed", error_code=error_code)
        metrics.increment(
            "runtime_inflight_operations",
            labels={"operation": op_name},
            value=-1,
        )
        logger.warning(
            "runtime_operation_failed correlation_id=%s operation=%s request_id=%s error_code=%s",
            corr_id,
            op_name,
            req_id,
            error_code,
        )
        return failure
    except Exception as exc:
        code = ErrorCode.RUNTIME_REPLAY_FAILED if op_name == RuntimeOperation.PENDING_REPLAY.value else ErrorCode.INTERNAL_UNEXPECTED
        failure = Result.fail_from_exception(
            exc,
            fallback_code=code,
            fallback_message="Runtime operation failed",
            fallback_details={
                "entity": "runtime_operation",
                "operation": op_name,
                "cause": "exception",
                "request_id": req_id,
                "correlation_id": corr_id,
            },
        )
        error_code = failure.error.code if failure.error else None
        metrics.increment(
            "runtime_operation_total",
            labels=build_operation_labels(
                operation=op_name,
                transport="telegram",
                result="failed",
                error_code=error_code,
                mode=dispatch_mode,
                runner=dispatch_runner,
            ),
        )
        if op_name == RuntimeOperation.PENDING_REPLAY.value:
            metrics.increment(
                "runtime_pending_replay_total",
                labels=build_operation_labels(
                    operation=op_name,
                    transport="telegram",
                    result="failed",
                    error_code=error_code,
                    mode=dispatch_mode,
                    runner=dispatch_runner,
                ),
            )
        timer.observe(result="failed", error_code=error_code)
        metrics.increment(
            "runtime_inflight_operations",
            labels={"operation": op_name},
            value=-1,
        )
        logger.exception(
            "runtime_operation_failed correlation_id=%s operation=%s request_id=%s error_code=%s",
            corr_id,
            op_name,
            req_id,
            error_code,
        )
        return failure

    completed = not chain_result.had_error
    pending_saved = bool(save_pending_on_unauthorized and chain_result.had_error)
    replay_scheduled = bool(op_name == RuntimeOperation.PENDING_REPLAY.value and chain_result.had_error)
    result_label = "success" if completed else "failed"
    metrics.increment(
        "runtime_operation_total",
        labels=build_operation_labels(
            operation=op_name,
            transport="telegram",
            result=result_label,
            mode=dispatch_mode,
            runner=dispatch_runner,
        ),
    )
    if op_name == RuntimeOperation.PENDING_REPLAY.value:
        metrics.increment(
            "runtime_pending_replay_total",
            labels=build_operation_labels(
                operation=op_name,
                transport="telegram",
                result=result_label,
                mode=dispatch_mode,
                runner=dispatch_runner,
            ),
        )
    timer.observe(result=result_label)
    metrics.increment(
        "runtime_inflight_operations",
        labels={"operation": op_name},
        value=-1,
    )
    logger.info(
        "runtime_operation_finished correlation_id=%s operation=%s request_id=%s result=%s completed=%s",
        corr_id,
        op_name,
        req_id,
        result_label,
        completed,
    )
    return Result.ok(
        RuntimeOperationResult(
            operation=op_name,
            request_id=req_id,
            completed=completed,
            queued=bool(chain_result.completed_roles > 0),
            busy_acquired=bool(chain_result.completed_roles > 0),
            pending_saved=pending_saved,
            replay_scheduled=replay_scheduled,
            transitions=_build_runtime_transitions(
                operation=op_name,
                trigger=chain_origin,
                request_id=req_id,
                completed=completed,
                pending_saved=pending_saved,
                replay_scheduled=replay_scheduled,
            ),
        )
    )
