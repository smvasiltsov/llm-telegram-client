from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.application.observability import ensure_correlation_id
from app.models import QaQuestion

logger = logging.getLogger("application.qa_runtime_bridge_core")


@dataclass(frozen=True)
class BridgeExecutionResult:
    answer_text: str
    role_name: str | None
    answer_team_role_id: int | None
    append_orchestrator_feed: bool = True


@dataclass(frozen=True)
class QaRuntimeExecutionRequest:
    team_id: int
    execution_user_id: int
    role: Any
    session_token: str
    user_text: str
    correlation_id: str
    question_id: str


@dataclass(frozen=True)
class QaRuntimeExecutionResponse:
    response_text: str
    busy_acquired: bool
    team_role_id: int | None


class QaRuntimeExecutionAdapter(Protocol):
    async def execute(self, *, runtime: Any, request: QaRuntimeExecutionRequest) -> QaRuntimeExecutionResponse: ...


def resolve_role_requires_auth(*, runtime: Any, team_id: int, role: Any, correlation_id: str | None = None) -> bool:
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


def resolve_execution_auth_token(runtime: Any, question: QaQuestion, correlation_id: str):
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


def resolve_execution_session(*, runtime: Any, question: QaQuestion, team_id: int, role: Any, correlation_id: str) -> tuple[int, str]:
    requires_auth = resolve_role_requires_auth(
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
    execution_user_id, auth_token = resolve_execution_auth_token(runtime, question, correlation_id)
    return execution_user_id, runtime.cipher.decrypt(auth_token.encrypted_token)


async def execute_question_through_adapter(
    *,
    runtime: Any,
    question: QaQuestion,
    correlation_id: str,
    adapter: QaRuntimeExecutionAdapter,
) -> BridgeExecutionResult:
    storage = runtime.storage
    if question.target_team_role_id is None:
        raise RuntimeError("dispatch_rejected:missing_target_team_role_id")
    identity = storage.resolve_team_role_identity(int(question.target_team_role_id))
    if identity is None:
        raise ValueError(f"Team role not found: team_role_id={question.target_team_role_id}")
    team_id, role_id = identity
    role = storage.get_role_by_id(int(role_id))
    execution_user_id, session_token = resolve_execution_session(
        runtime=runtime,
        question=question,
        team_id=int(team_id),
        role=role,
        correlation_id=correlation_id,
    )
    response = await adapter.execute(
        runtime=runtime,
        request=QaRuntimeExecutionRequest(
            team_id=int(team_id),
            execution_user_id=int(execution_user_id),
            role=role,
            session_token=session_token,
            user_text=str(question.text),
            correlation_id=correlation_id,
            question_id=question.question_id,
        ),
    )
    if bool(response.busy_acquired) and response.team_role_id is not None:
        try:
            runtime.role_runtime_status_service.release_busy(
                team_role_id=int(response.team_role_id),
                release_reason="api_bridge_answered",
            )
        except Exception:
            logger.exception(
                "qa_bridge_release_busy_failed correlation_id=%s question_id=%s team_role_id=%s",
                correlation_id,
                question.question_id,
                response.team_role_id,
            )

    return BridgeExecutionResult(
        answer_text=str(response.response_text),
        role_name=role.public_name(),
        answer_team_role_id=int(response.team_role_id or question.target_team_role_id),
        append_orchestrator_feed=True,
    )


__all__ = [
    "BridgeExecutionResult",
    "QaRuntimeExecutionAdapter",
    "QaRuntimeExecutionRequest",
    "QaRuntimeExecutionResponse",
    "execute_question_through_adapter",
    "resolve_execution_auth_token",
    "resolve_execution_session",
    "resolve_role_requires_auth",
]
