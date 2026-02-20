from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.llm_executor import LLMExecutor
from app.llm_router import MissingUserField
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.plugins import PluginManager
from app.services.formatting import format_with_header_raw, render_llm_text, send_formatted_with_fallback
from app.services.plugin_pipeline import build_plugin_reply_markup
from app.services.prompt_builder import build_llm_content, resolve_provider_model, role_requires_auth
from app.roles_registry import seed_group_roles
from app.router import route_message
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.storage import Storage
from app.utils import split_message
from app.handlers.messages_common import (
    _handle_missing_user_field,
    _is_unauthorized,
    _request_token_for_user,
    _runtime,
)

logger = logging.getLogger("bot")


async def handle_group_buffered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not update.effective_chat or not update.effective_user:
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
    if require_bot_mention:
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
    auth = storage.get_auth_token(user_id)
    provider_registry = _runtime(context).provider_registry
    default_provider_id = _runtime(context).default_provider_id
    provider_models = _runtime(context).provider_models
    provider_model_map = _runtime(context).provider_model_map
    requires_auth = False
    for role in route.roles:
        group_role = storage.get_group_role(chat_id, role.role_id)
        if provider_models:
            model_override = resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                group_role.model_override or role.llm_model,
            )
        else:
            model_override = group_role.model_override or role.llm_model
        if role_requires_auth(provider_registry, model_override, default_provider_id):
            requires_auth = True
            break

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
    llm_executor: LLMExecutor = _runtime(context).llm_executor
    resolver: SessionResolver = _runtime(context).session_resolver

    provider_models = _runtime(context).provider_models
    provider_model_map = _runtime(context).provider_model_map
    reply_to_message_id = items[0].message_id
    for role in route.roles:
        try:
            group_role = storage.get_group_role(chat_id, role.role_id)
            if provider_models:
                model_override = resolve_provider_model(
                    provider_models,
                    provider_model_map,
                    provider_registry,
                    group_role.model_override or role.llm_model,
                )
            else:
                logger.warning("Provider model list is empty for role=%s", role.role_name)
                model_override = group_role.model_override or role.llm_model
            logger.info(
                "flush role=%s model_override=%s",
                role.role_name,
                model_override,
            )
            content = build_llm_content(
                route.content,
                group_role.user_prompt_suffix,
                group_role.user_reply_prefix,
                reply_text,
            )
            session_id = await resolver.resolve(
                user_id,
                chat_id,
                role,
                session_token,
                model_override=model_override,
            )
            response_text = await llm_executor.send_with_retries(
                session_id=session_id,
                session_token=session_token,
                content=content,
                role=role,
                model_override=model_override,
            )
        except MissingUserField as exc:
            role_name = "__all__" if route.is_all else role.role_name
            await _handle_missing_user_field(
                user_id,
                chat_id,
                reply_to_message_id,
                role_name,
                route.content,
                reply_text,
                exc,
                context,
            )
            return
        except Exception as exc:
            if _is_unauthorized(exc):
                pending: PendingStore = _runtime(context).pending_store
                role_name = "__all__" if route.is_all else route.roles[0].role_name
                pending.save(
                    user_id,
                    chat_id,
                    reply_to_message_id,
                    role_name,
                    route.content,
                    reply_text=reply_text,
                )
                storage.set_user_authorized(user_id, False)
                await _request_token_for_user(chat_id, user_id, context)
                return
            logger.exception("LLM request failed user_id=%s role=%s", user_id, role.role_name)
            await context.bot.send_message(chat_id=chat_id, text="Ошибка при запросе к LLM. Попробуй позже.")
            continue
        allow_raw_html = bool(_runtime(context).allow_raw_html)
        formatting_mode = str(_runtime(context).formatting_mode)
        plugin_manager: PluginManager = _runtime(context).plugin_manager
        payload = {
            "text": response_text,
            "parse_mode": formatting_mode,
            "reply_markup": None,
        }
        logger.info(
            "plugin pre buffered user_id=%s role=%s provider=%s text_len=%s",
            user_id,
            role.role_name,
            llm_executor.provider_id_for_model(model_override),
            len(response_text),
        )
        ctx_payload = {
            "chat_id": chat_id,
            "user_id": user_id,
            "role_id": role.role_id,
            "role_name": role.role_name,
            "provider_id": llm_executor.provider_id_for_model(model_override),
            "model_id": model_override,
            "store_text": storage.save_plugin_text,
        }
        payload = plugin_manager.apply_postprocess(payload, ctx_payload)
        response_text = str(payload.get("text", ""))
        reply_markup = payload.get("reply_markup")
        logger.info(
            "plugin post buffered user_id=%s role=%s text_len=%s reply_markup=%s",
            user_id,
            role.role_name,
            len(response_text),
            bool(reply_markup),
        )
        final_reply_markup = build_plugin_reply_markup(
            reply_markup,
            is_private=chat_id > 0,
            logger=logger,
            log_ctx={"user_id": user_id, "role": role.role_name},
        )
        rendered = render_llm_text(response_text, formatting_mode, allow_raw_html)
        full_text = format_with_header_raw(None, rendered)
        for idx, chunk in enumerate(split_message(full_text)):
            await send_formatted_with_fallback(
                context.bot,
                chat_id,
                chunk,
                reply_to_message_id=reply_to_message_id,
                reply_markup=final_reply_markup if idx == 0 else None,
                allow_raw_html=allow_raw_html,
                formatting_mode=formatting_mode,
            )
