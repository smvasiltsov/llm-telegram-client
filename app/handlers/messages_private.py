from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.auth import AuthService
from app.llm_executor import LLMExecutor
from app.llm_router import MissingUserField
from app.llm_providers import ProviderUserField, model_label
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.services.formatting import format_with_header
from app.services.prompt_builder import build_llm_content, resolve_provider_model, role_requires_auth
from app.services.tool_exec import execute_bash_command
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.storage import Storage
from app.utils import split_message
from app.handlers.messages_common import (
    _handle_missing_user_field,
    _is_unauthorized,
    _request_token_for_user,
    _request_user_field_for_user,
    _runtime,
)

logger = logging.getLogger("bot")


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    storage: Storage = _runtime(context).storage
    user = update.effective_user
    if not user:
        return
    logger.info("private msg user_id=%s text=%r", user.id, update.message.text)
    storage.upsert_user(user.id, user.username)
    pending_bash_auth: dict[int, dict[str, Any]] = _runtime(context).pending_bash_auth
    pending_bash = pending_bash_auth.get(user.id)
    if pending_bash:
        pending_cmd = str(pending_bash.get("cmd", ""))
        pending_chat_id = int(pending_bash.get("chat_id", user.id))
        password_value = update.message.text.strip()
        if password_value.startswith("/") and password_value.lower() not in {"cancel", "/cancel"}:
            return
        if password_value.lower() in {"cancel", "/cancel"}:
            storage.log_tool_run(
                telegram_user_id=user.id,
                chat_id=pending_chat_id,
                source="telegram",
                tool_name="bash",
                command_text=pending_cmd,
                role="privileged",
                requires_password=True,
                trusted=False,
                status="auth_cancelled",
            )
            pending_bash_auth.pop(user.id, None)
            await update.message.reply_text("Подтверждение команды отменено.")
            return
        expected_password = str(_runtime(context).tools_bash_password).strip()
        if not expected_password:
            storage.log_tool_run(
                telegram_user_id=user.id,
                chat_id=pending_chat_id,
                source="telegram",
                tool_name="bash",
                command_text=pending_cmd,
                role="privileged",
                requires_password=True,
                trusted=False,
                status="auth_not_configured",
                error_text="BASH_DANGEROUS_PASSWORD is empty",
            )
            pending_bash_auth.pop(user.id, None)
            await update.message.reply_text("Пароль не настроен. Укажите BASH_DANGEROUS_PASSWORD в .env.")
            return
        if password_value != expected_password:
            storage.log_tool_run(
                telegram_user_id=user.id,
                chat_id=pending_chat_id,
                source="telegram",
                tool_name="bash",
                command_text=pending_cmd,
                role="privileged",
                requires_password=True,
                trusted=False,
                status="auth_failed",
            )
            await update.message.reply_text("Неверный пароль. Попробуйте ещё раз или отправьте /cancel.")
            return
        pending_bash_auth.pop(user.id, None)
        await update.message.reply_text("Пароль принят. Выполняю команду.")
        await execute_bash_command(
            cmd=pending_cmd,
            caller_id=user.id,
            chat_id=pending_chat_id,
            message_id=int(pending_bash["message_id"]),
            trusted=True,
            tool_service=_runtime(context).tool_service,
            storage=_runtime(context).storage,
            bash_cwd_by_user=_runtime(context).bash_cwd_by_user,
            bot=context.bot,
        )
        return

    pending_prompts = _runtime(context).pending_prompts
    pending_roles = _runtime(context).pending_role_ops
    pending_fields: PendingUserFieldStore = _runtime(context).pending_user_fields
    pending_field_state = pending_fields.get(user.id)
    logger.info(
        "private pending state user_id=%s pending_field=%s pending_msg=%s",
        user.id,
        bool(pending_field_state),
        bool(_runtime(context).pending_store.peek(user.id)),
    )
    if (
        update.message.text.strip().startswith("/")
        and not pending_field_state
        and user.id not in pending_prompts
        and user.id not in pending_roles
    ):
        return
    pending_msg = _runtime(context).pending_store.peek(user.id)
    auth = storage.get_auth_token(user.id)
    if pending_field_state:
        state = pending_field_state
        value = update.message.text.strip()
        if not value:
            await update.message.reply_text("Значение не может быть пустым. Попробуй ещё раз.")
            return
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1].strip()
        if str(state.get("key", "")).lower() == "auth_token":
            lowered = value.lower()
            if lowered.startswith("cookie:"):
                value = value.split(":", 1)[1].strip()
            lowered = value.lower()
            if lowered.startswith("sessionid="):
                value = value.split("=", 1)[1].strip()
            if ";" in value:
                value = value.split(";", 1)[0].strip()
        pending_fields.delete(user.id)
        storage.set_provider_user_value(state["provider_id"], state["key"], state["role_id"], value)
        await update.message.reply_text("Проверяю значение и пытаюсь ответить на сообщение из группы.")
        processed = await _process_pending_message_for_user(user.id, context)
        if processed:
            return
        if pending_fields.get(user.id):
            storage.delete_provider_user_value(state["provider_id"], state["key"], state["role_id"])
            return
        pending_msg = _runtime(context).pending_store.peek(user.id)
        storage.delete_provider_user_value(state["provider_id"], state["key"], state["role_id"])
        if not pending_msg:
            pending_fields.delete(user.id)
            await update.message.reply_text(
                "Нет ожидающего сообщения из группы. Отправь запрос в группу ещё раз."
            )
            return
        pending_fields.save(
            telegram_user_id=user.id,
            provider_id=str(state["provider_id"]),
            key=str(state["key"]),
            role_id=state["role_id"] if isinstance(state["role_id"], int) or state["role_id"] is None else None,
            prompt=str(state.get("prompt") or "Введите значение ещё раз."),
            chat_id=int(state.get("chat_id", user.id)),
        )
        await update.message.reply_text("Не удалось использовать значение. Проверь и отправь ещё раз.")
        scope = "provider" if state.get("role_id") is None else "role"
        await _request_user_field_for_user(
            int(state.get("chat_id", user.id)),
            user.id,
            ProviderUserField(
                key=str(state["key"]),
                prompt=str(state.get("prompt") or "Введите значение ещё раз."),
                scope=scope,
            ),
            context,
        )
        return
    if user.id in pending_prompts and (not pending_msg or (auth and auth.is_authorized)):
        private_buffer: MessageBuffer = _runtime(context).private_buffer
        started = await private_buffer.add(
            update.effective_chat.id,
            user.id,
            update.message.message_id,
            update.message.text,
            start=True,
        )
        if started:
            should_schedule = await private_buffer.mark_scheduled(update.effective_chat.id, user.id)
            if should_schedule:
                asyncio.create_task(_flush_private_buffered(update.effective_chat.id, user.id, context))
        return
    if user.id in pending_roles:
        state = pending_roles[user.id]
        if state["step"] in {"suffix", "reply_prefix"}:
            private_buffer: MessageBuffer = _runtime(context).private_buffer
            started = await private_buffer.add(
                update.effective_chat.id,
                user.id,
                update.message.message_id,
                update.message.text,
                start=True,
            )
            if started:
                should_schedule = await private_buffer.mark_scheduled(update.effective_chat.id, user.id)
                if should_schedule:
                    asyncio.create_task(_flush_private_buffered(update.effective_chat.id, user.id, context))
            return
        text = update.message.text.strip()
        if state["step"] == "name":
            role_name = text.lstrip("@").strip()
            if not re.match(r"^[A-Za-z0-9_]+$", role_name):
                await update.message.reply_text("Имя роли должно быть латиницей, цифрами или _. Попробуй еще раз.")
                return
            role_name = role_name.lower()
            if storage.role_exists(role_name):
                if state.get("mode") == "rename":
                    current_role = storage.get_role_by_id(state["role_id"])
                    if role_name != current_role.role_name:
                        await update.message.reply_text("Роль с таким именем уже существует. Укажи другое имя.")
                        return
                else:
                    await update.message.reply_text("Роль с таким именем уже существует. Укажи другое имя.")
                    return
            state["role_name"] = role_name
            if state["mode"] == "rename":
                storage.update_role_name(state["role_id"], role_name)
                pending_roles.pop(user.id, None)
                await update.message.reply_text(f"Роль переименована в @{role_name}.")
                return
            if state["mode"] == "clone":
                source_role = storage.get_role_by_id(state["source_role_id"])
                source_group_role = storage.get_group_role(state["source_group_id"], source_role.role_id)
                target_group_id = state["target_group_id"]
                role = storage.upsert_role(
                    role_name=role_name,
                    description=source_role.description,
                    base_system_prompt=source_role.base_system_prompt,
                    extra_instruction=source_role.extra_instruction,
                    llm_model=source_role.llm_model,
                    is_active=True,
                )
                storage.ensure_group_role(target_group_id, role.role_id)
                storage.set_group_role_prompt(
                    target_group_id,
                    role.role_id,
                    source_group_role.system_prompt_override,
                )
                storage.set_group_role_model(
                    target_group_id,
                    role.role_id,
                    source_group_role.model_override,
                )
                storage.set_group_role_user_prompt_suffix(
                    target_group_id,
                    role.role_id,
                    source_group_role.user_prompt_suffix,
                )
                storage.set_group_role_user_reply_prefix(
                    target_group_id,
                    role.role_id,
                    source_group_role.user_reply_prefix,
                )
                pending_roles.pop(user.id, None)
                await update.message.reply_text(
                    f"Роль @{role.role_name} добавлена в группу {target_group_id}."
                )
                return
            state["prompt"] = ""
            state["step"] = "model_select"
            provider_models = _runtime(context).provider_models
            provider_registry = _runtime(context).provider_registry
            if not provider_models:
                await update.message.reply_text("Список моделей не настроен в llm_providers.")
                return
            buttons = []
            for model in provider_models:
                provider = provider_registry.get(model.provider_id)
                label = model_label(model, provider)
                buttons.append([InlineKeyboardButton(text=label, callback_data=f"addrole_model:{model.full_id}")])
            buttons.append([InlineKeyboardButton(text="Без модели", callback_data="addrole_model:__skip__")])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{state['target_group_id']}")])
            await update.message.reply_text(
                "Выбери LLM-модель для роли:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return
        if state["step"] == "model_select":
            await update.message.reply_text("Выбери модель кнопкой ниже.")
            return
        if state["step"] == "display":
            await update.message.reply_text("Этот пункт больше не используется.")
            pending_roles.pop(user.id, None)
            return
        if state["step"] == "suffix":
            suffix = text
            if suffix.lower() == "clear":
                suffix = None
            storage.set_group_role_user_prompt_suffix(state["target_group_id"], state["role_id"], suffix)
            pending_roles.pop(user.id, None)
            role = storage.get_role_by_id(state["role_id"])
            await update.message.reply_text(
                f"Инструкция к сообщениям для @{role.role_name} обновлена."
            )
            return
        if state["step"] == "reply_prefix":
            reply_prefix = text
            if reply_prefix.lower() == "clear":
                reply_prefix = None
            storage.set_group_role_user_reply_prefix(state["target_group_id"], state["role_id"], reply_prefix)
            pending_roles.pop(user.id, None)
            role = storage.get_role_by_id(state["role_id"])
            await update.message.reply_text(
                f"Инструкция для реплаев для @{role.role_name} обновлена."
            )
            return

    token = update.message.text.strip()
    if not token:
        await update.message.reply_text("Пришли токен в следующем сообщении.")
        return

    auth_service: AuthService = _runtime(context).auth_service
    pending: PendingStore = _runtime(context).pending_store
    pending_msg = pending.peek(user.id)
    group_id = pending_msg[0] if pending_msg else None
    ok = await auth_service.validate_and_store(user.id, token, group_id)
    if not ok:
        await update.message.reply_text("Токен не прошел проверку. Попробуй еще раз.")
        return

    await update.message.reply_text("Токен сохранен. Сейчас отвечу на последнее сообщение из группы.")
    processed = await _process_pending_message_for_user(user.id, context)
    if not processed:
        await update.message.reply_text(
            "Нет ожидающего сообщения из группы. Отправь запрос в группу ещё раз."
        )


async def _flush_private_buffered(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    private_buffer: MessageBuffer = _runtime(context).private_buffer
    items = await private_buffer.wait_and_collect(chat_id, user_id)
    if not items:
        return
    combined_text = "\n".join(item.content for item in items).strip()
    if not combined_text:
        return
    await _process_pending_private_text(user_id, chat_id, combined_text, context)


async def _process_pending_private_text(
    user_id: int,
    chat_id: int,
    text: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    storage: Storage = _runtime(context).storage
    pending_prompts = _runtime(context).pending_prompts
    pending_roles = _runtime(context).pending_role_ops
    pending_msg = _runtime(context).pending_store.peek(user_id)
    auth = storage.get_auth_token(user_id)

    if user_id in pending_prompts and (not pending_msg or (auth and auth.is_authorized)):
        group_id, role_id = pending_prompts.pop(user_id)
        raw_prompt = text.strip()
        if not raw_prompt:
            await context.bot.send_message(chat_id=chat_id, text="Промпт не может быть пустым.")
            return True
        is_clear = raw_prompt.lower() in {"clear", "skip"}
        prompt = "" if is_clear else raw_prompt
        storage.set_group_role_prompt(group_id, role_id, prompt)
        role = storage.get_role_by_id(role_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Промпт роли @{role.role_name} для группы {group_id} обновлён.",
        )
        return True

    if user_id in pending_roles and (not pending_msg or (auth and auth.is_authorized)):
        state = pending_roles[user_id]
        if state["step"] == "suffix":
            suffix = text.strip()
            if not suffix:
                await context.bot.send_message(chat_id=chat_id, text="Инструкция не может быть пустой.")
                return True
            if suffix.lower() == "clear":
                suffix = None
            storage.set_group_role_user_prompt_suffix(state["target_group_id"], state["role_id"], suffix)
            pending_roles.pop(user_id, None)
            role = storage.get_role_by_id(state["role_id"])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Инструкция к сообщениям для @{role.role_name} обновлена.",
            )
            return True
        if state["step"] == "reply_prefix":
            reply_prefix = text.strip()
            if not reply_prefix:
                await context.bot.send_message(chat_id=chat_id, text="Инструкция не может быть пустой.")
                return True
            if reply_prefix.lower() == "clear":
                reply_prefix = None
            storage.set_group_role_user_reply_prefix(state["target_group_id"], state["role_id"], reply_prefix)
            pending_roles.pop(user_id, None)
            role = storage.get_role_by_id(state["role_id"])
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Инструкция для реплаев для @{role.role_name} обновлена.",
            )
            return True

    return False


async def _process_pending_message_for_user(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    pending: PendingStore = _runtime(context).pending_store
    pending_msg = pending.peek(user_id)
    if not pending_msg:
        logger.info("pending message not found user_id=%s", user_id)
        return False
    chat_id, message_id, role_name, content, reply_text = pending_msg
    storage: Storage = _runtime(context).storage
    roles = storage.list_roles_for_group(chat_id)
    if role_name == "__all__":
        target_roles = roles
    else:
        role = next((r for r in roles if r.role_name == role_name), None)
        if not role:
            logger.info("pending role not found user_id=%s role_name=%s", user_id, role_name)
            return False
        target_roles = [role]

    provider_registry = _runtime(context).provider_registry
    default_provider_id = _runtime(context).default_provider_id
    provider_models = _runtime(context).provider_models
    provider_model_map = _runtime(context).provider_model_map
    auth = storage.get_auth_token(user_id)
    requires_auth = False
    for role in target_roles:
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
        await _request_token_for_user(chat_id, user_id, context)
        return False

    cipher: TokenCipher = _runtime(context).cipher
    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    llm_executor: LLMExecutor = _runtime(context).llm_executor
    resolver: SessionResolver = _runtime(context).session_resolver

    had_error = False
    for role in target_roles:
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
            session_id = await resolver.resolve(
                user_id,
                chat_id,
                role,
                session_token,
                model_override=model_override,
            )
            content_with_context = build_llm_content(
                content,
                group_role.user_prompt_suffix,
                group_role.user_reply_prefix,
                reply_text,
            )
            response_text = await llm_executor.send_with_retries(
                session_id=session_id,
                session_token=session_token,
                content=content_with_context,
                role=role,
                model_override=model_override,
            )
        except MissingUserField as exc:
            await _handle_missing_user_field(
                user_id,
                chat_id,
                message_id,
                role_name,
                content,
                reply_text,
                exc,
                context,
            )
            return False
        except Exception as exc:
            if _is_unauthorized(exc):
                storage.set_user_authorized(user_id, False)
                await _request_token_for_user(chat_id, user_id, context)
                return False
            logger.exception("LLM request failed for pending message user_id=%s role=%s", user_id, role.role_name)
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ошибка при запросе к LLM. Попробуй позже.",
                reply_to_message_id=message_id,
            )
            had_error = True
            continue

        full_text = format_with_header(None, response_text)
        for chunk in split_message(full_text):
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_to_message_id=message_id,
                parse_mode=ParseMode.HTML,
            )

    if not had_error:
        pending.pop(user_id)
        return True
    return False
