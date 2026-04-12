from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.application.use_cases.group_runtime import build_group_flush_plan, prepare_group_buffer_plan
from app.interfaces.telegram_runtime_client import resolve_runtime_client
from app.message_buffer import MessageBuffer
from app.handlers.messages_common import (
    _ensure_runtime_correlation_id,
    _ensure_update_correlation_id,
    _request_token_for_user,
    _runtime,
)

logger = logging.getLogger("bot")


async def handle_group_buffered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not update.effective_chat or not update.effective_user:
        return
    if update.effective_user.is_bot:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return
    correlation_id = _ensure_update_correlation_id(update, context)
    logger.info(
        "group msg correlation_id=%s chat_id=%s title=%r user_id=%s username=%r text=%r",
        correlation_id,
        chat.id,
        chat.title,
        update.effective_user.id,
        update.effective_user.username,
        update.message.text,
    )
    runtime = _runtime(context)
    runtime_client = resolve_runtime_client(context.application.bot_data)
    prep_result = runtime_client.prepare_group_buffer(
        context=context,
        chat_id=chat.id,
        chat_title=chat.title,
        user_id=update.effective_user.id,
        text=update.message.text,
    )
    if prep_result.is_error or prep_result.value is None:
        logger.warning("group_prepare_failed chat_id=%s user_id=%s", chat.id, update.effective_user.id)
        return
    prep = prep_result.value
    if prep.orchestrator_role_name:
        logger.info(
            "orchestrator active chat_id=%s role=%s role_id=%s",
            chat.id,
            prep.orchestrator_role_name,
            "n/a",
        )
    owner_user_id = runtime.owner_user_id
    logger.info(
        "group msg owner_user_id=%s matched=%s",
        owner_user_id,
        update.effective_user.id == owner_user_id,
    )
    if not prep.should_process:
        return

    bot_username = runtime.bot_username
    text = update.message.text
    require_bot_mention = runtime.require_bot_mention
    mentioned = f"@{bot_username.lower()}" in text.lower()
    should_start = prep.should_start
    logger.info(
        "group msg routing require_bot_mention=%s mentioned=%s should_start=%s roles=%s",
        require_bot_mention,
        mentioned,
        should_start,
        list(prep.role_names),
    )

    buffer: MessageBuffer = _runtime(context).message_buffer
    started = await buffer.add(
        chat.id,
        update.effective_user.id,
        update.message.message_id,
        text,
        start=should_start,
        reply_text=update.message.reply_to_message.text if update.message.reply_to_message else None,
    )
    logger.info("group msg buffered started=%s", started)
    if started:
        should_schedule = await buffer.mark_scheduled(chat.id, update.effective_user.id)
        logger.info("group msg buffered scheduled=%s", should_schedule)
        if should_schedule:
            asyncio.create_task(_flush_buffered(chat.id, update.effective_user.id, context))


async def _flush_buffered(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    correlation_id = _ensure_runtime_correlation_id()
    buffer: MessageBuffer = _runtime(context).message_buffer
    items = await buffer.wait_and_collect(chat_id, user_id)
    if not items:
        logger.info("flush empty chat_id=%s user_id=%s", chat_id, user_id)
        return
    combined_text = "\n".join(item.content for item in items)
    reply_text = next((item.reply_text for item in items if item.reply_text), None)
    logger.info(
        "flush correlation_id=%s chat_id=%s user_id=%s items=%s reply_text=%s combined_len=%s",
        correlation_id,
        chat_id,
        user_id,
        len(items),
        bool(reply_text),
        len(combined_text),
    )

    runtime_client = resolve_runtime_client(context.application.bot_data)
    await runtime_client.flush_group_buffered(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        combined_text=combined_text,
        reply_text=reply_text,
        first_message_id=items[0].message_id,
        correlation_id=correlation_id,
        request_token_fn=_request_token_for_user,
    )
