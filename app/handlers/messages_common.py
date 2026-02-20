from __future__ import annotations

import logging

import httpx
from telegram.ext import ContextTypes

from app.llm_router import MissingUserField
from app.llm_providers import ProviderUserField
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.runtime import RuntimeContext

logger = logging.getLogger("bot")


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> RuntimeContext:
    return context.application.bot_data["runtime"]


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
    message_id: int,
    role_name: str,
    content: str,
    reply_text: str | None,
    exc: MissingUserField,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    pending: PendingStore = _runtime(context).pending_store
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
        message_id=message_id,
        role_name=role_name,
        content=content,
        reply_text=reply_text,
    )
    pending_fields: PendingUserFieldStore = _runtime(context).pending_user_fields
    pending_fields.save(
        telegram_user_id=user_id,
        provider_id=exc.provider_id,
        key=exc.field.key,
        role_id=exc.role_id,
        prompt=exc.field.prompt,
        chat_id=chat_id,
    )
    logger.info("pending user field saved user_id=%s provider=%s key=%s", user_id, exc.provider_id, exc.field.key)
    await _request_user_field_for_user(chat_id, user_id, exc.field, context)


def _is_unauthorized(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    return response is not None and response.status_code == 401
