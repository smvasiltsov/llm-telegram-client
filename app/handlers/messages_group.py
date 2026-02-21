from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.services.role_pipeline import roles_require_auth, run_chain
from app.roles_registry import seed_group_roles
from app.router import RouteResult, route_message
from app.security import TokenCipher
from app.storage import Storage
from app.utils import extract_role_mentions, strip_bot_mention
from app.handlers.messages_common import (
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
    logger.info(
        "group msg chat_id=%s title=%r user_id=%s username=%r text=%r",
        chat.id,
        chat.title,
        update.effective_user.id,
        update.effective_user.username,
        update.message.text,
    )
    storage: Storage = _runtime(context).storage
    storage.upsert_group(chat.id, chat.title)
    seed_group_roles(storage, chat.id)
    orchestrator_group_role = storage.get_enabled_orchestrator_for_group(chat.id)
    orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id) if orchestrator_group_role else None
    if orchestrator_role is not None:
        logger.info(
            "orchestrator active chat_id=%s role=%s role_id=%s",
            chat.id,
            orchestrator_role.role_name,
            orchestrator_role.role_id,
        )
    owner_user_id = _runtime(context).owner_user_id
    logger.info(
        "group msg owner_user_id=%s matched=%s",
        owner_user_id,
        update.effective_user.id == owner_user_id,
    )
    if update.effective_user.id != owner_user_id:
        return

    bot_username = _runtime(context).bot_username
    text = update.message.text
    require_bot_mention = _runtime(context).require_bot_mention
    mentioned = f"@{bot_username.lower()}" in text.lower()
    if orchestrator_role is not None:
        should_start = True
    elif require_bot_mention:
        should_start = mentioned
    else:
        roles = storage.list_roles_for_group(chat.id)
        lowered = text.lower()
        should_start = "@all" in lowered or any(f"@{role.role_name.lower()}" in lowered for role in roles)
    logger.info(
        "group msg routing require_bot_mention=%s mentioned=%s should_start=%s roles=%s",
        require_bot_mention,
        mentioned,
        should_start,
        [role.role_name for role in storage.list_roles_for_group(chat.id)],
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
    buffer: MessageBuffer = _runtime(context).message_buffer
    items = await buffer.wait_and_collect(chat_id, user_id)
    if not items:
        logger.info("flush empty chat_id=%s user_id=%s", chat_id, user_id)
        return
    combined_text = "\n".join(item.content for item in items)
    reply_text = next((item.reply_text for item in items if item.reply_text), None)
    logger.info(
        "flush chat_id=%s user_id=%s items=%s reply_text=%s combined_len=%s",
        chat_id,
        user_id,
        len(items),
        bool(reply_text),
        len(combined_text),
    )

    bot_username = _runtime(context).bot_username
    storage: Storage = _runtime(context).storage
    roles = storage.list_roles_for_group(chat_id)
    owner_user_id = _runtime(context).owner_user_id
    require_bot_mention = _runtime(context).require_bot_mention
    orchestrator_group_role = storage.get_enabled_orchestrator_for_group(chat_id)
    orchestrator_role = storage.get_role_by_id(orchestrator_group_role.role_id) if orchestrator_group_role else None
    if orchestrator_role is not None:
        cleaned = strip_bot_mention(combined_text, bot_username)
        role_map = {r.role_name.lower(): r for r in roles}
        is_all = "@all" in cleaned.lower()
        mentioned_names = extract_role_mentions(cleaned, set(role_map.keys()))
        selected_roles: list = []
        if is_all:
            selected_roles = [r for r in roles if r.role_id != orchestrator_role.role_id]
        else:
            seen_ids: set[int] = set()
            for name in mentioned_names:
                target = role_map.get(name.lower())
                if not target:
                    continue
                if target.role_id == orchestrator_role.role_id:
                    continue
                if target.role_id in seen_ids:
                    continue
                selected_roles.append(target)
                seen_ids.add(target.role_id)
        should_route_to_orchestrator = len(selected_roles) == 0
        if should_route_to_orchestrator:
            selected_roles = [orchestrator_role]
        logger.info(
            "orchestrator route chat_id=%s orchestrator_role=%s mentioned_roles=%s is_all=%s fanout=%s direct_to_orchestrator=%s",
            chat_id,
            orchestrator_role.role_name,
            mentioned_names,
            is_all,
            [r.role_name for r in selected_roles],
            should_route_to_orchestrator,
        )
        route = RouteResult(
            roles=selected_roles,
            content=combined_text.strip(),
            is_all=is_all,
        )
    else:
        route = route_message(
            combined_text,
            bot_username,
            roles,
            owner_user_id=owner_user_id,
            author_user_id=user_id,
            require_bot_mention=require_bot_mention,
        )
    logger.info("flush route result=%s", "ok" if route else "none")
    if not route:
        return
    if not route.content:
        await context.bot.send_message(chat_id=chat_id, text="Напиши сообщение после роли.")
        return

    storage.upsert_user(user_id, None)
    actor = storage.get_user(user_id)
    auth = storage.get_auth_token(user_id)
    requires_auth = roles_require_auth(
        context=context,
        chat_id=chat_id,
        roles=route.roles,
    )

    if requires_auth and (not auth or not auth.is_authorized):
        pending: PendingStore = _runtime(context).pending_store
        role_name = "__all__" if route.is_all else route.roles[0].role_name
        pending.save(
            user_id,
            chat_id,
            items[0].message_id,
            role_name,
            route.content,
            reply_text=reply_text,
        )
        await _request_token_for_user(chat_id, user_id, context)
        return

    cipher: TokenCipher = _runtime(context).cipher
    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    reply_to_message_id = items[0].message_id
    await run_chain(
        context=context,
        chat_id=chat_id,
        user_id=user_id,
        session_token=session_token,
        roles=route.roles,
        user_text=route.content,
        reply_text=reply_text,
        actor_username=actor.username if actor else None,
        reply_to_message_id=reply_to_message_id,
        is_all=route.is_all,
        apply_plugins=True,
        save_pending_on_unauthorized=True,
        pending_role_name="__all__" if route.is_all else route.roles[0].role_name,
        allow_orchestrator_post_event=True,
        chain_origin="group",
    )
