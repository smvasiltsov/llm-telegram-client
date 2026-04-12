from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from app.llm_router import MissingUserField
from app.models import Role

logger = logging.getLogger("bot")


@dataclass(frozen=True)
class SessionRecoveryResult:
    response_text: str
    old_session_id: str
    new_session_id: str


def _is_not_found(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    return response is not None and response.status_code == 404


async def handle_missing_user_field(
    *,
    runtime: Any,
    user_id: int,
    chat_id: int,
    team_id: int,
    message_id: int,
    role_name: str,
    content: str,
    reply_text: str | None,
    exc: MissingUserField,
    request_user_field_fn: Callable[[int, int, Any], Awaitable[None]],
) -> None:
    pending = runtime.pending_store
    logger.info(
        "missing user field provider=%s key=%s scope=%s role_id=%s chat_id=%s",
        exc.provider_id,
        exc.field.key,
        exc.field.scope,
        exc.role_id,
        chat_id,
    )
    pending.save(
        telegram_user_id=user_id,
        chat_id=chat_id,
        team_id=team_id,
        message_id=message_id,
        role_name=role_name,
        content=content,
        reply_text=reply_text,
    )
    pending_fields = runtime.pending_user_fields
    existing_pending_field = pending_fields.get(user_id)
    same_field_pending = bool(
        existing_pending_field
        and str(existing_pending_field.get("provider_id", "")) == exc.provider_id
        and str(existing_pending_field.get("key", "")) == exc.field.key
        and existing_pending_field.get("role_id") == exc.role_id
        and existing_pending_field.get("team_id") == team_id
    )
    pending_fields.save(
        telegram_user_id=user_id,
        provider_id=exc.provider_id,
        key=exc.field.key,
        role_id=exc.role_id,
        prompt=exc.field.prompt,
        chat_id=chat_id,
        team_id=team_id,
    )
    logger.info("pending user field saved user_id=%s provider=%s key=%s", user_id, exc.provider_id, exc.field.key)
    if same_field_pending:
        logger.info(
            "pending user field prompt suppressed (already requested) user_id=%s provider=%s key=%s",
            user_id,
            exc.provider_id,
            exc.field.key,
        )
        return
    await request_user_field_fn(chat_id, user_id, exc.field)


async def recover_stale_session_and_resend(
    *,
    runtime: Any,
    exc: Exception,
    user_id: int,
    chat_id: int,
    team_id: int,
    role: Role,
    session_id: str,
    session_token: str,
    model_override: str | None,
    content: str,
) -> SessionRecoveryResult | None:
    if not _is_not_found(exc):
        return None
    llm_router = runtime.llm_router
    if not llm_router.supports(model_override, "list_sessions"):
        return None
    logger.warning(
        "Session send failed with 404. Trying one-time recovery user_id=%s chat_id=%s role=%s session_id=%s",
        user_id,
        chat_id,
        role.role_name,
        session_id,
    )
    session_ids = await llm_router.list_sessions(session_token, model_override=model_override)
    existing_session_ids = set(session_ids)
    if session_id in existing_session_ids:
        logger.warning(
            "Session %s still exists in provider list, skip recovery role=%s",
            session_id,
            role.role_name,
        )
        return None
    resolver = runtime.session_resolver
    llm_executor = runtime.llm_executor
    new_session_id = await resolver.ensure_session(
        telegram_user_id=user_id,
        team_id=team_id,
        role=role,
        session_token=session_token,
        model_override=model_override,
        existing_session_ids=existing_session_ids,
    )
    if new_session_id == session_id:
        logger.warning(
            "Session recovery returned same session_id=%s role=%s",
            session_id,
            role.role_name,
        )
        return None
    response_text = await llm_executor.send_with_retries(
        session_id=new_session_id,
        session_token=session_token,
        content=content,
        role=role,
        model_override=model_override,
        team_role_id=int(team_role_id),
        retries=0,
    )
    return SessionRecoveryResult(
        response_text=response_text,
        old_session_id=session_id,
        new_session_id=new_session_id,
    )
