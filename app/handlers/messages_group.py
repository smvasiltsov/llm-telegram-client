from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.application.dependencies import (
    resolve_pending_replay_dependencies,
    resolve_runtime_orchestration_dependencies,
    resolve_storage_uow_dependencies,
)
from app.application.contracts import log_structured_error
from app.application.use_cases.runtime_orchestration import execute_run_chain_operation
from app.application.use_cases.group_runtime import (
    GroupFlushInput,
    build_group_flush_plan,
    prepare_group_buffer_plan,
)
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.services.role_pipeline import roles_require_auth
from app.storage import Storage
from app.handlers.messages_common import (
    _ensure_runtime_correlation_id,
    _ensure_update_correlation_id,
    _request_token_for_user,
    _runtime,
)

logger = logging.getLogger("bot")

def _resolve_storage(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    storage_result = resolve_storage_uow_dependencies(context.application.bot_data)
    if storage_result.is_ok and storage_result.value is not None:
        return storage_result.value.storage
    return _runtime(context).storage


def _resolve_pending_store(context: ContextTypes.DEFAULT_TYPE) -> PendingStore:
    pending_result = resolve_pending_replay_dependencies(context.application.bot_data)
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_store
    return _runtime(context).pending_store


def _resolve_cipher(context: ContextTypes.DEFAULT_TYPE):
    orchestration_result = resolve_runtime_orchestration_dependencies(context.application.bot_data)
    if orchestration_result.is_ok and orchestration_result.value is not None:
        return orchestration_result.value.cipher
    return _runtime(context).cipher


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
    storage: Storage = _resolve_storage(context)
    prep_result = prepare_group_buffer_plan(
        storage=storage,
        runtime=runtime,
        chat_id=chat.id,
        chat_title=chat.title,
        user_id=update.effective_user.id,
        text=update.message.text,
    )
    if prep_result.is_error or prep_result.value is None:
        log_structured_error(
            logger,
            event="group_prepare_failed",
            error=prep_result.error,
            extra={"chat_id": chat.id, "user_id": update.effective_user.id},
        )
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

    runtime = _runtime(context)
    storage: Storage = _resolve_storage(context)
    flush_result = build_group_flush_plan(
        storage=storage,
        runtime=runtime,
        data=GroupFlushInput(
            chat_id=chat_id,
            user_id=user_id,
            combined_text=combined_text,
            reply_text=reply_text,
            first_message_id=items[0].message_id,
            bot_username=runtime.bot_username,
            owner_user_id=runtime.owner_user_id,
            require_bot_mention=runtime.require_bot_mention,
        ),
        roles_require_auth_fn=lambda **kwargs: roles_require_auth(context=context, **kwargs),
        cipher=_resolve_cipher(context),
    )
    if flush_result.is_error or flush_result.value is None:
        log_structured_error(
            logger,
            event="group_flush_failed",
            error=flush_result.error,
            extra={"chat_id": chat_id, "user_id": user_id},
        )
        return
    plan = flush_result.value
    if plan.action == "skip" and plan.team_id is None:
        logger.warning("flush skipped: team binding not found chat_id=%s", chat_id)
        return
    logger.info("flush route result=%s action=%s", "ok" if plan.route else "none", plan.action)
    if plan.action == "skip":
        return
    if plan.action == "send_hint":
        await context.bot.send_message(chat_id=chat_id, text="Напиши сообщение после роли.")
        return
    if plan.action == "request_token":
        if plan.team_id is None or plan.route is None or plan.role_name_for_pending is None or plan.content_for_pending is None:
            logger.warning("flush token request skipped due to incomplete plan chat_id=%s user_id=%s", chat_id, user_id)
            return
        pending: PendingStore = _resolve_pending_store(context)
        pending.save(
            user_id,
            chat_id,
            items[0].message_id,
            plan.role_name_for_pending,
            plan.content_for_pending,
            reply_text=reply_text,
            team_id=plan.team_id,
        )
        await _request_token_for_user(chat_id, user_id, context)
        return

    if plan.action != "dispatch_chain" or plan.team_id is None or plan.route is None:
        logger.warning("flush dispatch skipped due to incomplete plan chat_id=%s user_id=%s", chat_id, user_id)
        return
    reply_to_message_id = plan.reply_to_message_id if plan.reply_to_message_id is not None else items[0].message_id
    await execute_run_chain_operation(
        context=context,
        team_id=plan.team_id,
        chat_id=chat_id,
        user_id=user_id,
        session_token=plan.session_token,
        roles=plan.route.roles,
        user_text=plan.route.content,
        reply_text=reply_text,
        actor_username="user",
        reply_to_message_id=reply_to_message_id,
        is_all=plan.route.is_all,
        apply_plugins=True,
        save_pending_on_unauthorized=True,
        pending_role_name=plan.role_name_for_pending or ("__all__" if plan.route.is_all else plan.route.roles[0].public_name()),
        allow_orchestrator_post_event=True,
        chain_origin="group",
        correlation_id=correlation_id,
    )
