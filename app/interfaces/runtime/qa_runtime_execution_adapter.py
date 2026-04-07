from __future__ import annotations

from types import SimpleNamespace

from app.application.contracts.runtime_ops import RuntimeOperation
from app.application.use_cases.qa_runtime_bridge_core import (
    QaRuntimeExecutionRequest,
    QaRuntimeExecutionResponse,
)


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


class TelegramQaRuntimeExecutionAdapter:
    async def execute(self, *, runtime, request: QaRuntimeExecutionRequest) -> QaRuntimeExecutionResponse:
        # Lazy import keeps API schema/tests loadable even when Telegram deps are missing.
        from app.services.role_pipeline import execute_role_request

        context = SimpleNamespace(
            application=_BridgeApp(runtime),
            bot=_NoopBot(),
            correlation_id=request.correlation_id,
        )
        result = await execute_role_request(
            context=context,
            team_id=int(request.team_id),
            user_id=int(request.execution_user_id),
            role=request.role,
            session_token=request.session_token,
            user_text=request.user_text,
            reply_text=None,
            actor_username=f"api_user_{request.execution_user_id}",
            trigger_type="api_question",
            mentioned_roles=[request.role.public_name()],
            recipient=request.role.public_name(),
            wait_until_available=True,
            queue_request_id=request.question_id,
            correlation_id=request.correlation_id,
            operation=RuntimeOperation.RUN_CHAIN.value,
        )
        return QaRuntimeExecutionResponse(
            response_text=str(result.response_text),
            busy_acquired=bool(result.busy_acquired),
            team_role_id=(int(result.team_role_id) if result.team_role_id is not None else None),
        )


__all__ = ["TelegramQaRuntimeExecutionAdapter"]
