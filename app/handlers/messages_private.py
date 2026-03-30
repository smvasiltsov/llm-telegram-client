from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.auth import AuthService
from app.llm_providers import ProviderUserField, model_label
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.role_catalog_service import master_role_exists, refresh_role_catalog, update_master_role_json
from app.services.role_pipeline import roles_require_auth, run_chain
from app.services.tool_exec import execute_bash_command
from app.security import TokenCipher
from app.storage import Storage
from app.handlers.messages_common import (
    _request_token_for_user,
    _request_user_field_for_user,
    _runtime,
)

logger = logging.getLogger("bot")
_MAX_ROLE_SCOPED_REPLAY_PROMPT_RETRIES = 2


def _resolve_team_id_for_chat(storage: Storage, chat_id: int) -> int:
    team_id = storage.resolve_team_id_by_telegram_chat(chat_id)
    if team_id is not None:
        return team_id
    return storage.upsert_telegram_team_binding(chat_id, None, is_active=True)


def _set_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object], value: str) -> None:
    provider_id = str(state["provider_id"])
    key = str(state["key"])
    role_id = state.get("role_id")
    if isinstance(role_id, int):
        team_id = state.get("team_id")
        if not isinstance(team_id, int):
            raise ValueError("pending role-scoped field has no team_id")
        team_role_id = storage.resolve_team_role_id(team_id, role_id, ensure_exists=True)
        if team_role_id is None:
            raise ValueError(f"team_role_id not found for team_id={team_id} role_id={role_id}")
        storage.set_provider_user_value_by_team_role(provider_id, key, int(team_role_id), value)
        return
    storage.set_provider_user_value(provider_id, key, None, value)


def _delete_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object]) -> None:
    provider_id = str(state["provider_id"])
    key = str(state["key"])
    role_id = state.get("role_id")
    if isinstance(role_id, int):
        team_id = state.get("team_id")
        if not isinstance(team_id, int):
            return
        team_role_id = storage.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        storage.delete_provider_user_value_by_team_role(provider_id, key, int(team_role_id))
        return
    storage.delete_provider_user_value(provider_id, key, None)


def _is_role_scoped_pending_field(state: dict[str, object]) -> bool:
    return isinstance(state.get("role_id"), int)


def _is_same_pending_field_state(left: dict[str, object], right: dict[str, object]) -> bool:
    return (
        str(left.get("provider_id", "")) == str(right.get("provider_id", ""))
        and str(left.get("key", "")) == str(right.get("key", ""))
        and left.get("role_id") == right.get("role_id")
        and left.get("team_id") == right.get("team_id")
    )


def _pending_replay_counter_key(
    user_id: int,
    state: dict[str, object],
    pending_msg: dict[str, object] | None,
) -> tuple[object, ...]:
    if pending_msg is None:
        return (
            user_id,
            state.get("provider_id"),
            state.get("key"),
            state.get("role_id"),
            state.get("team_id"),
            None,
            None,
            None,
        )
    return (
        user_id,
        state.get("provider_id"),
        state.get("key"),
        state.get("role_id"),
        state.get("team_id"),
        pending_msg.get("chat_id"),
        pending_msg.get("message_id"),
        pending_msg.get("role_name"),
    )


def _pending_replay_counters(context: ContextTypes.DEFAULT_TYPE) -> dict[tuple[object, ...], int]:
    runtime = _runtime(context)
    counters = getattr(runtime, "pending_replay_attempts", None)
    if isinstance(counters, dict):
        return counters
    counters = {}
    setattr(runtime, "pending_replay_attempts", counters)
    return counters


def _clear_pending_replay_counters(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    counters = _pending_replay_counters(context)
    keys_to_drop = [key for key in counters if key and key[0] == user_id]
    for key in keys_to_drop:
        counters.pop(key, None)


def _increment_pending_replay_counter(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: dict[str, object],
    pending_msg: dict[str, object] | None,
) -> int:
    counters = _pending_replay_counters(context)
    key = _pending_replay_counter_key(user_id, state, pending_msg)
    current = int(counters.get(key, 0))
    updated = current + 1
    counters[key] = updated
    return updated


def _is_root_dir_pending_field(state: dict[str, object]) -> bool:
    return str(state.get("key", "")).strip().lower() == "root_dir"


def _validate_pending_field_value(state: dict[str, object], value: str) -> str | None:
    key = str(state.get("key", "")).strip().lower()
    if key != "root_dir":
        return None
    root_path = Path(value).expanduser()
    if not root_path.exists():
        return f"Путь не существует: {root_path}"
    if not root_path.is_dir():
        return f"Путь не является директорией: {root_path}"
    return None


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    storage: Storage = _runtime(context).storage
    refresh_role_catalog(runtime=_runtime(context), storage=storage)
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
        validation_error = _validate_pending_field_value(state, value)
        if validation_error:
            await update.message.reply_text(f"{validation_error}\nВведи корректный путь ещё раз.")
            return
        pending_fields.delete(user.id)
        try:
            _set_provider_user_field_from_pending_state(storage, state, value)
        except Exception:
            logger.exception(
                "failed to save pending user field user_id=%s provider=%s key=%s role_id=%s team_id=%s",
                user.id,
                state.get("provider_id"),
                state.get("key"),
                state.get("role_id"),
                state.get("team_id"),
            )
            pending_fields.save(
                telegram_user_id=user.id,
                provider_id=str(state["provider_id"]),
                key=str(state["key"]),
                role_id=state["role_id"] if isinstance(state["role_id"], int) or state["role_id"] is None else None,
                prompt=str(state.get("prompt") or "Введите значение ещё раз."),
                chat_id=int(state.get("chat_id", user.id)),
                team_id=int(state["team_id"]) if state.get("team_id") is not None else None,
            )
            await update.message.reply_text("Не удалось сохранить значение. Попробуй ещё раз.")
            return
        if _is_root_dir_pending_field(state):
            logger.info(
                "root_dir_saved user_id=%s team_id=%s role_id=%s",
                user.id,
                state.get("team_id"),
                state.get("role_id"),
            )
        await update.message.reply_text("Проверяю значение и пытаюсь ответить на сообщение из группы.")
        processed = await _process_pending_message_for_user(user.id, context)
        if processed:
            _clear_pending_replay_counters(context, user.id)
            return
        replay_pending_state = pending_fields.get(user.id)
        if replay_pending_state:
            if _is_role_scoped_pending_field(state) and _is_same_pending_field_state(replay_pending_state, state):
                replay_pending_msg = _runtime(context).pending_store.peek_record(user.id)
                attempts = _increment_pending_replay_counter(context, user.id, state, replay_pending_msg)
                if _is_root_dir_pending_field(state):
                    logger.warning(
                        "root_dir_replay_failed user_id=%s team_id=%s role_id=%s attempt=%s",
                        user.id,
                        state.get("team_id"),
                        state.get("role_id"),
                        attempts,
                    )
                if attempts <= _MAX_ROLE_SCOPED_REPLAY_PROMPT_RETRIES:
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
                if _is_root_dir_pending_field(state):
                    logger.warning(
                        "root_dir_prompt_repeated_suppressed user_id=%s team_id=%s role_id=%s attempts=%s",
                        user.id,
                        state.get("team_id"),
                        state.get("role_id"),
                        attempts,
                    )
                _runtime(context).pending_store.pop_record(user.id)
                pending_fields.delete(user.id)
                _clear_pending_replay_counters(context, user.id)
                await update.message.reply_text(
                    "Не удалось автоматически продолжить после нескольких попыток. "
                    "Отправь запрос в группу ещё раз."
                )
                return
            if not _is_role_scoped_pending_field(state):
                _delete_provider_user_field_from_pending_state(storage, state)
            _clear_pending_replay_counters(context, user.id)
            return
        pending_msg = _runtime(context).pending_store.peek(user.id)
        if not _is_role_scoped_pending_field(state):
            _delete_provider_user_field_from_pending_state(storage, state)
        if not pending_msg:
            pending_fields.delete(user.id)
            _clear_pending_replay_counters(context, user.id)
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
            team_id=int(state["team_id"]) if state.get("team_id") is not None else None,
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
        _clear_pending_replay_counters(context, user.id)
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
        if state.get("mode") == "master_create":
            if state["step"] == "name":
                role_name = text.lstrip("@").strip().lower()
                if not re.match(r"^[A-Za-z0-9_]+$", role_name):
                    await update.message.reply_text("Имя роли должно быть латиницей, цифрами или _. Попробуй еще раз.")
                    return
                if master_role_exists(_runtime(context), role_name) or storage.role_exists(role_name):
                    await update.message.reply_text("Master-role с таким именем уже существует. Укажи другое имя.")
                    return
                state["role_name"] = role_name
                state["step"] = "prompt"
                await update.message.reply_text("Отправь system prompt для master-role (или 'skip').")
                return
            if state["step"] == "prompt":
                prompt = "" if text.lower() in {"skip", "clear"} else text
                state["prompt"] = prompt
                state["step"] = "instruction"
                await update.message.reply_text("Отправь instruction для master-role (или 'skip').")
                return
            if state["step"] == "instruction":
                instruction = "" if text.lower() in {"skip", "clear"} else text
                state["instruction"] = instruction
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
                    buttons.append([InlineKeyboardButton(text=label, callback_data=f"mrole_create_model:{model.full_id}")])
                buttons.append([InlineKeyboardButton(text="Без модели", callback_data="mrole_create_model:__skip__")])
                buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mroles:list")])
                await update.message.reply_text(
                    "Выбери LLM-модель для master-role:",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
                return
            if state["step"] == "model_select":
                await update.message.reply_text("Выбери модель кнопкой ниже.")
                return
        if state.get("mode") == "master_update":
            role_id = int(state["role_id"])
            role = storage.get_role_by_id(role_id)
            if state["step"] == "master_prompt":
                value = text
                if not value:
                    await update.message.reply_text("Системный промпт не может быть пустым.")
                    return
                if len(value) > 16000:
                    await update.message.reply_text("Системный промпт слишком длинный. Максимум: 16000 символов.")
                    return
                update_master_role_json(
                    runtime=_runtime(context),
                    storage=storage,
                    role_name=role.role_name,
                    base_system_prompt=value,
                )
                logger.info(
                    "master_role_updated user_id=%s role=%s changed_fields=%s operation=%s source=%s",
                    user.id,
                    role.role_name,
                    "base_system_prompt",
                    "set",
                    "private",
                )
                pending_roles.pop(user.id, None)
                await update.message.reply_text(f"Master system prompt для @{role.role_name} обновлён.")
                return
            if state["step"] == "master_suffix":
                value = text
                if not value:
                    await update.message.reply_text("Инструкция к сообщениям не может быть пустой.")
                    return
                if len(value) > 8000:
                    await update.message.reply_text("Инструкция слишком длинная. Максимум: 8000 символов.")
                    return
                update_master_role_json(
                    runtime=_runtime(context),
                    storage=storage,
                    role_name=role.role_name,
                    extra_instruction=value,
                )
                logger.info(
                    "master_role_updated user_id=%s role=%s changed_fields=%s operation=%s source=%s",
                    user.id,
                    role.role_name,
                    "extra_instruction",
                    "set",
                    "private",
                )
                pending_roles.pop(user.id, None)
                await update.message.reply_text(f"Master instruction для @{role.role_name} обновлена.")
                return
        if state["step"] == "name":
            role_name = text.lstrip("@").strip()
            if not re.match(r"^[A-Za-z0-9_]+$", role_name):
                await update.message.reply_text("Имя роли должно быть латиницей, цифрами или _. Попробуй еще раз.")
                return
            role_name = role_name.lower()
            target_group_id = int(state["target_group_id"])
            target_team_id = _resolve_team_id_for_chat(storage, target_group_id)
            exclude_role_id = int(state["role_id"]) if state.get("mode") == "rename" else None
            if storage.team_role_name_exists(target_team_id, role_name, exclude_role_id=exclude_role_id):
                await update.message.reply_text("Роль с таким именем уже существует в этой группе. Укажи другое имя.")
                return
            state["role_name"] = role_name
            if state["mode"] == "rename":
                storage.set_team_role_display_name(target_team_id, state["role_id"], role_name)
                pending_roles.pop(user.id, None)
                await update.message.reply_text(f"Роль переименована в @{role_name}.")
                return
            pending_roles.pop(user.id, None)
            await update.message.reply_text("Этот сценарий больше не используется. Добавляй роли через список master-role.")
            return
        if state["step"] == "display":
            await update.message.reply_text("Этот пункт больше не используется.")
            pending_roles.pop(user.id, None)
            return
        if state["step"] == "suffix":
            suffix = text
            if suffix.lower() == "clear":
                suffix = None
            target_team_id = _resolve_team_id_for_chat(storage, int(state["target_group_id"]))
            storage.set_team_role_user_prompt_suffix(target_team_id, state["role_id"], suffix)
            pending_roles.pop(user.id, None)
            await update.message.reply_text(
                f"Инструкция к сообщениям для "
                f"@{storage.get_team_role_name(target_team_id, state['role_id'])} обновлена."
            )
            return
        if state["step"] == "reply_prefix":
            reply_prefix = text
            if reply_prefix.lower() == "clear":
                reply_prefix = None
            target_team_id = _resolve_team_id_for_chat(storage, int(state["target_group_id"]))
            storage.set_team_role_user_reply_prefix(target_team_id, state["role_id"], reply_prefix)
            pending_roles.pop(user.id, None)
            await update.message.reply_text(
                f"Инструкция для реплаев для "
                f"@{storage.get_team_role_name(target_team_id, state['role_id'])} обновлена."
            )
            return

    token = update.message.text.strip()
    if not token:
        await update.message.reply_text("Пришли токен в следующем сообщении.")
        return

    auth_service: AuthService = _runtime(context).auth_service
    pending: PendingStore = _runtime(context).pending_store
    pending_msg = pending.peek_record(user.id)
    if not pending_msg:
        # Ignore free-form private messages when bot is not waiting for token.
        return

    group_id = int(pending_msg["chat_id"])
    role_name = str(pending_msg["role_name"])
    pending_team_id = pending_msg.get("team_id")
    if pending_team_id is None:
        pending.pop_record(user.id)
        await update.message.reply_text("Ожидающее сообщение устарело. Отправь запрос в группу ещё раз.")
        return
    team_id = int(pending_team_id)
    roles_for_group = storage.list_roles_for_team(team_id)
    if role_name == "__all__":
        target_roles = roles_for_group
    else:
        target_roles = [role for role in roles_for_group if role.public_name() == role_name]
        if not target_roles:
            # Backward compatibility: pending rows may contain internal role_name.
            target_roles = [role for role in roles_for_group if role.role_name == role_name]
    if not target_roles:
        return

    requires_auth = roles_require_auth(
        context=context,
        team_id=team_id,
        roles=target_roles,
    )
    if not requires_auth:
        return

    ok = await auth_service.validate_and_store(user.id, token, team_id)
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
        team_id = _resolve_team_id_for_chat(storage, group_id)
        raw_prompt = text.strip()
        if not raw_prompt:
            await context.bot.send_message(chat_id=chat_id, text="Промпт не может быть пустым.")
            return True
        is_clear = raw_prompt.lower() in {"clear", "skip"}
        prompt = "" if is_clear else raw_prompt
        storage.set_team_role_prompt(team_id, role_id, prompt)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Промпт роли @{storage.get_team_role_name(team_id, role_id)} для группы {group_id} обновлён.",
        )
        return True

    if user_id in pending_roles and (not pending_msg or (auth and auth.is_authorized)):
        state = pending_roles[user_id]
        if state.get("mode") == "master_update":
            role_id = int(state["role_id"])
            role = storage.get_role_by_id(role_id)
            value = text.strip()
            if state["step"] == "master_prompt":
                if not value:
                    await context.bot.send_message(chat_id=chat_id, text="Системный промпт не может быть пустым.")
                    return True
                if len(value) > 16000:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Системный промпт слишком длинный. Максимум: 16000 символов.",
                    )
                    return True
                update_master_role_json(
                    runtime=_runtime(context),
                    storage=storage,
                    role_name=role.role_name,
                    base_system_prompt=value,
                )
                logger.info(
                    "master_role_updated user_id=%s role=%s changed_fields=%s operation=%s source=%s",
                    user_id,
                    role.role_name,
                    "base_system_prompt",
                    "set",
                    "private",
                )
                pending_roles.pop(user_id, None)
                await context.bot.send_message(chat_id=chat_id, text=f"Master system prompt для @{role.role_name} обновлён.")
                return True
            if state["step"] == "master_suffix":
                if not value:
                    await context.bot.send_message(chat_id=chat_id, text="Инструкция к сообщениям не может быть пустой.")
                    return True
                if len(value) > 8000:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Инструкция слишком длинная. Максимум: 8000 символов.",
                    )
                    return True
                update_master_role_json(
                    runtime=_runtime(context),
                    storage=storage,
                    role_name=role.role_name,
                    extra_instruction=value,
                )
                logger.info(
                    "master_role_updated user_id=%s role=%s changed_fields=%s operation=%s source=%s",
                    user_id,
                    role.role_name,
                    "extra_instruction",
                    "set",
                    "private",
                )
                pending_roles.pop(user_id, None)
                await context.bot.send_message(chat_id=chat_id, text=f"Master instruction для @{role.role_name} обновлена.")
                return True
        if state["step"] == "suffix":
            suffix = text.strip()
            if not suffix:
                await context.bot.send_message(chat_id=chat_id, text="Инструкция не может быть пустой.")
                return True
            if suffix.lower() == "clear":
                suffix = None
            target_team_id = _resolve_team_id_for_chat(storage, int(state["target_group_id"]))
            storage.set_team_role_user_prompt_suffix(target_team_id, state["role_id"], suffix)
            pending_roles.pop(user_id, None)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Инструкция к сообщениям для "
                    f"@{storage.get_team_role_name(target_team_id, state['role_id'])} обновлена."
                ),
            )
            return True
        if state["step"] == "reply_prefix":
            reply_prefix = text.strip()
            if not reply_prefix:
                await context.bot.send_message(chat_id=chat_id, text="Инструкция не может быть пустой.")
                return True
            if reply_prefix.lower() == "clear":
                reply_prefix = None
            target_team_id = _resolve_team_id_for_chat(storage, int(state["target_group_id"]))
            storage.set_team_role_user_reply_prefix(target_team_id, state["role_id"], reply_prefix)
            pending_roles.pop(user_id, None)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Инструкция для реплаев для "
                    f"@{storage.get_team_role_name(target_team_id, state['role_id'])} обновлена."
                ),
            )
            return True

    return False


async def _process_pending_message_for_user(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    pending: PendingStore = _runtime(context).pending_store
    pending_msg = pending.peek_record(user_id)
    if not pending_msg:
        _clear_pending_replay_counters(context, user_id)
        logger.info("pending message not found user_id=%s", user_id)
        return False
    original_pending_msg = pending_msg
    chat_id = int(pending_msg["chat_id"])
    message_id = int(pending_msg["message_id"])
    role_name = str(pending_msg["role_name"])
    content = str(pending_msg["content"])
    reply_text = pending_msg["reply_text"]
    storage: Storage = _runtime(context).storage
    refresh_role_catalog(runtime=_runtime(context), storage=storage)
    pending_team_id = pending_msg.get("team_id")
    if pending_team_id is None:
        pending.pop_record(user_id)
        _clear_pending_replay_counters(context, user_id)
        logger.warning("pending message dropped (missing team_id) user_id=%s chat_id=%s", user_id, chat_id)
        return False
    team_id = int(pending_team_id)
    roles = storage.list_roles_for_team(team_id)
    if role_name == "__all__":
        target_roles = roles
    else:
        role = next((r for r in roles if r.public_name() == role_name), None)
        if role is None:
            # Backward compatibility: pending rows may contain internal role_name.
            role = next((r for r in roles if r.role_name == role_name), None)
        if not role:
            _clear_pending_replay_counters(context, user_id)
            logger.info("pending role not found user_id=%s role_name=%s", user_id, role_name)
            return False
        target_roles = [role]

    auth = storage.get_auth_token(user_id)
    requires_auth = roles_require_auth(
        context=context,
        team_id=team_id,
        roles=target_roles,
    )
    if requires_auth and (not auth or not auth.is_authorized):
        await _request_token_for_user(chat_id, user_id, context)
        return False

    cipher: TokenCipher = _runtime(context).cipher
    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    chain_result = await run_chain(
        context=context,
        team_id=team_id,
        chat_id=chat_id,
        user_id=user_id,
        session_token=session_token,
        roles=target_roles,
        user_text=content,
        reply_text=reply_text,
        actor_username="user",
        reply_to_message_id=message_id,
        is_all=role_name == "__all__",
        apply_plugins=False,
        save_pending_on_unauthorized=False,
        pending_role_name=role_name,
        allow_orchestrator_post_event=chat_id < 0,
        chain_origin="pending",
    )

    if not chain_result.had_error:
        _clear_pending_replay_counters(context, user_id)
        current_pending_msg = pending.peek_record(user_id)
        if current_pending_msg == original_pending_msg:
            pending.pop_record(user_id)
        elif current_pending_msg is not None:
            logger.info(
                "pending message preserved user_id=%s old_role=%s new_role=%s",
                user_id,
                original_pending_msg[2],
                current_pending_msg[2],
            )
        return True
    return False
