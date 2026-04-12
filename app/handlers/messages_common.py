from __future__ import annotations

import logging
from typing import Any

import httpx
from telegram.ext import ContextTypes

from app.application.observability import ensure_correlation_id, get_correlation_id
from app.llm_router import MissingUserField
from app.models import Role
from app.llm_providers import ProviderUserField
from app.runtime import RuntimeContext
from app.services.runtime_message_flow import (
    SessionRecoveryResult,
    handle_missing_user_field as _runtime_handle_missing_user_field,
    recover_stale_session_and_resend as _runtime_recover_stale_session_and_resend,
)

logger = logging.getLogger("bot")


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> RuntimeContext:
    return context.application.bot_data["runtime"]


def _resolve_external_correlation_id(update: Any, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    if update is not None:
        value = getattr(update, "correlation_id", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = getattr(context, "correlation_id", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    if isinstance(bot_data, dict):
        for key in ("correlation_id", "x_correlation_id"):
            candidate = bot_data.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _ensure_update_correlation_id(update: Any, context: ContextTypes.DEFAULT_TYPE) -> str:
    external = _resolve_external_correlation_id(update, context)
    return ensure_correlation_id(external)


def _ensure_runtime_correlation_id() -> str:
    return ensure_correlation_id(get_correlation_id())


def _is_unauthorized(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    return response is not None and response.status_code == 401


async def _request_token_for_user(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Пришли, пожалуйста, авторизационный токен для LLM.",
        )
    except Exception:
        logger.exception("Failed to send DM token request user_id=%s", user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не смог написать в личку. Напиши мне в личные сообщения.",
        )


async def _request_user_field_for_user(
    chat_id: int,
    user_id: int,
    field: ProviderUserField,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.info("requesting user field user_id=%s key=%s chat_id=%s", user_id, field.key, chat_id)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=field.prompt,
        )
    except Exception:
        logger.exception("Failed to send DM user field request user_id=%s key=%s", user_id, field.key)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Не смог написать в личку. Напиши мне в личные сообщения.",
        )


async def _handle_missing_user_field(
    user_id: int,
    chat_id: int,
    team_id: int,
    message_id: int,
    role_name: str,
    content: str,
    reply_text: str | None,
    exc: MissingUserField,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await _runtime_handle_missing_user_field(
        runtime=_runtime(context),
        user_id=user_id,
        chat_id=chat_id,
        team_id=team_id,
        message_id=message_id,
        role_name=role_name,
        content=content,
        reply_text=reply_text,
        exc=exc,
        request_user_field_fn=lambda req_chat_id, req_user_id, field: _request_user_field_for_user(
            req_chat_id,
            req_user_id,
            field,
            context,
        ),
    )


async def _recover_stale_session_and_resend(
    *,
    exc: Exception,
    user_id: int,
    chat_id: int,
    team_id: int,
    role: Role,
    session_id: str,
    session_token: str,
    model_override: str | None,
    content: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> SessionRecoveryResult | None:
    return await _runtime_recover_stale_session_and_resend(
        runtime=_runtime(context),
        exc=exc,
        user_id=user_id,
        chat_id=chat_id,
        team_id=team_id,
        role=role,
        session_id=session_id,
        session_token=session_token,
        model_override=model_override,
        content=content,
    )
