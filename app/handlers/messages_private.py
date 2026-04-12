from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.application.dependencies import (
    resolve_pending_replay_dependencies,
    resolve_runtime_orchestration_dependencies,
    resolve_storage_uow_dependencies,
    resolve_tooling_dependencies,
)
from app.application.contracts import ErrorCode, Result, log_structured_error, to_telegram_message
from app.application.use_cases.private_pending_field import (
    build_pending_field_replay_plan,
    delete_provider_user_field_from_pending_state,
    is_role_scoped_pending_field,
    is_root_dir_pending_field,
    normalize_pending_field_value,
    set_provider_user_field_from_pending_state,
    validate_pending_field_value,
)
from app.interfaces.telegram_runtime_client import resolve_runtime_client
from app.auth import AuthService
from app.llm_providers import ProviderUserField, model_label
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.role_catalog_service import master_role_exists, refresh_role_catalog, update_master_role_json
from app.services.role_pipeline import roles_require_auth
from app.services.tool_exec import execute_bash_command
from app.security import TokenCipher
from app.storage import Storage
from app.handlers.messages_common import (
    _ensure_runtime_correlation_id,
    _ensure_update_correlation_id,
    _request_token_for_user,
    _request_user_field_for_user,
    _runtime,
)

logger = logging.getLogger("bot")
_MAX_ROLE_SCOPED_REPLAY_PROMPT_RETRIES = 2


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


def _resolve_pending_user_fields(context: ContextTypes.DEFAULT_TYPE) -> PendingUserFieldStore:
    pending_result = resolve_pending_replay_dependencies(context.application.bot_data)
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_user_fields
    return _runtime(context).pending_user_fields


def _resolve_pending_prompts(context: ContextTypes.DEFAULT_TYPE) -> dict[int, tuple[int, int]]:
    pending_result = resolve_pending_replay_dependencies(context.application.bot_data)
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_prompts
    return _runtime(context).pending_prompts


def _resolve_pending_role_ops(context: ContextTypes.DEFAULT_TYPE) -> dict[int, dict[str, Any]]:
    pending_result = resolve_pending_replay_dependencies(context.application.bot_data)
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_role_ops
    return _runtime(context).pending_role_ops


def _resolve_cipher(context: ContextTypes.DEFAULT_TYPE) -> TokenCipher:
    orchestration_result = resolve_runtime_orchestration_dependencies(context.application.bot_data)
    if orchestration_result.is_ok and orchestration_result.value is not None:
        return orchestration_result.value.cipher
    return _runtime(context).cipher


def _resolve_provider_models(context: ContextTypes.DEFAULT_TYPE) -> list[Any]:
    orchestration_result = resolve_runtime_orchestration_dependencies(context.application.bot_data)
    if orchestration_result.is_ok and orchestration_result.value is not None:
        return orchestration_result.value.provider_models
    return _runtime(context).provider_models


def _resolve_provider_registry(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    orchestration_result = resolve_runtime_orchestration_dependencies(context.application.bot_data)
    if orchestration_result.is_ok and orchestration_result.value is not None:
        return orchestration_result.value.provider_registry
    return _runtime(context).provider_registry


def _resolve_tool_service(context: ContextTypes.DEFAULT_TYPE):
    tooling_result = resolve_tooling_dependencies(context.application.bot_data)
    if tooling_result.is_ok and tooling_result.value is not None:
        return tooling_result.value.tool_service
    return _runtime(context).tool_service


def _resolve_pending_bash_auth(context: ContextTypes.DEFAULT_TYPE) -> dict[int, dict[str, Any]]:
    tooling_result = resolve_tooling_dependencies(context.application.bot_data)
    if tooling_result.is_ok and tooling_result.value is not None:
        return tooling_result.value.pending_bash_auth
    return _runtime(context).pending_bash_auth


def _resolve_bash_cwd_by_user(context: ContextTypes.DEFAULT_TYPE) -> dict[int, str]:
    tooling_result = resolve_tooling_dependencies(context.application.bot_data)
    if tooling_result.is_ok and tooling_result.value is not None:
        return tooling_result.value.bash_cwd_by_user
    return _runtime(context).bash_cwd_by_user


def _resolve_tools_bash_password(context: ContextTypes.DEFAULT_TYPE) -> str:
    tooling_result = resolve_tooling_dependencies(context.application.bot_data)
    if tooling_result.is_ok and tooling_result.value is not None:
        return tooling_result.value.tools_bash_password
    return str(_runtime(context).tools_bash_password)


def _resolve_team_id_for_chat(storage: Storage, chat_id: int) -> int:
    team_id = storage.resolve_team_id_by_telegram_chat(chat_id)
    if team_id is not None:
        return team_id
    with storage.transaction(immediate=True):
        return storage.upsert_telegram_team_binding(chat_id, None, is_active=True)


def _set_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object], value: str) -> None:
    with storage.transaction(immediate=True):
        set_provider_user_field_from_pending_state(storage, state, value)


async def _set_provider_user_field_from_pending_state_via_api(
    context: ContextTypes.DEFAULT_TYPE,
    storage: Storage,
    state: dict[str, object],
    value: str,
) -> bool:
    runtime = _runtime(context)
    if not bool(getattr(runtime, "telegram_thin_client_enabled", False)):
        return False
    key = str(state.get("key", "")).strip().lower()
    if key not in {"working_dir", "root_dir"}:
        return False
    team_id = state.get("team_id")
    role_id = state.get("role_id")
    if not isinstance(team_id, int) or not isinstance(role_id, int):
        return False
    team_role_id = storage.resolve_team_role_id(team_id, role_id)
    if team_role_id is None:
        raise ValueError(f"team_role_id not found for team_id={team_id} role_id={role_id}")
    payload_key = "working_dir" if key == "working_dir" else "root_dir"
    endpoint = f"/api/v1/team-roles/{int(team_role_id)}/{'working-dir' if key == 'working_dir' else 'root-dir'}"
    base_url = str(getattr(runtime, "telegram_api_base_url", "") or "").strip()
    if not base_url:
        raise ValueError("telegram_api_base_url is empty")
    timeout_sec = max(1, int(getattr(runtime, "telegram_api_timeout_sec", 30) or 30))
    headers = {
        "X-Owner-User-Id": str(int(runtime.owner_user_id)),
        "X-Correlation-Id": _ensure_runtime_correlation_id(),
    }
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=float(timeout_sec)) as client:
        response = await client.put(endpoint, headers=headers, json={payload_key: value})
    if response.status_code != 200:
        raise ValueError(f"failed to save {payload_key} via api status={response.status_code} body={response.text[:200]}")
    return True


def _delete_provider_user_field_from_pending_state(storage: Storage, state: dict[str, object]) -> None:
    with storage.transaction(immediate=True):
        delete_provider_user_field_from_pending_state(storage, state)


def _is_role_scoped_pending_field(state: dict[str, object]) -> bool:
    return is_role_scoped_pending_field(state)


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
    return is_root_dir_pending_field(state)


def _is_working_or_root_pending_field(state: dict[str, object]) -> bool:
    key = str(state.get("key", "")).strip().lower()
    return key in {"working_dir", "root_dir"}


def _validate_pending_field_value(state: dict[str, object], value: str) -> str | None:
    return validate_pending_field_value(state, value)


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    correlation_id = _ensure_update_correlation_id(update, context)
    storage: Storage = _resolve_storage(context)
    refresh_role_catalog(runtime=_runtime(context), storage=storage)
    user = update.effective_user
    if not user:
        return
    try:
        logger.info("private msg correlation_id=%s user_id=%s text=%r", correlation_id, user.id, update.message.text)
        with storage.transaction(immediate=True):
            storage.upsert_user(user.id, user.username)
        pending_bash_auth: dict[int, dict[str, Any]] = _resolve_pending_bash_auth(context)
        pending_bash = pending_bash_auth.get(user.id)
        if pending_bash:
            pending_cmd = str(pending_bash.get("cmd", ""))
            pending_chat_id = int(pending_bash.get("chat_id", user.id))
            password_value = update.message.text.strip()
            if password_value.startswith("/") and password_value.lower() not in {"cancel", "/cancel"}:
                return
            if password_value.lower() in {"cancel", "/cancel"}:
                with storage.transaction(immediate=True):
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
            expected_password = _resolve_tools_bash_password(context).strip()
            if not expected_password:
                with storage.transaction(immediate=True):
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
                with storage.transaction(immediate=True):
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
                tool_service=_resolve_tool_service(context),
                storage=storage,
                bash_cwd_by_user=_resolve_bash_cwd_by_user(context),
                bot=context.bot,
            )
            return

        pending_prompts = _resolve_pending_prompts(context)
        pending_roles = _resolve_pending_role_ops(context)
        pending_fields: PendingUserFieldStore = _resolve_pending_user_fields(context)
        pending_store = _resolve_pending_store(context)
        pending_field_state = pending_fields.get(user.id)
        logger.info(
            "private pending state user_id=%s pending_field=%s pending_msg=%s",
            user.id,
            bool(pending_field_state),
            bool(pending_store.peek(user.id)),
        )
        if (
            update.message.text.strip().startswith("/")
            and not pending_field_state
            and user.id not in pending_prompts
            and user.id not in pending_roles
        ):
            return
        pending_msg = pending_store.peek(user.id)
        auth = storage.get_auth_token(user.id)
        if pending_field_state:
            state = pending_field_state
            normalized = normalize_pending_field_value(state, update.message.text)
            if normalized.is_error or normalized.value is None:
                log_structured_error(
                    logger,
                    event="private_pending_field_normalize_failed",
                    error=normalized.error,
                    extra={"user_id": user.id, "provider_id": state.get("provider_id"), "key": state.get("key")},
                )
                await update.message.reply_text(to_telegram_message(normalized.error, "Некорректное значение"))
                return
            value = normalized.value
            validation_error = _validate_pending_field_value(state, value)
            if validation_error:
                await update.message.reply_text(f"{validation_error}\nВведи корректный путь ещё раз.")
                return
            pending_fields.delete(user.id)
            try:
                saved_via_api = await _set_provider_user_field_from_pending_state_via_api(context, storage, state, value)
                if not saved_via_api:
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
            pending_msg = pending_store.peek(user.id)
            replay_pending_msg = pending_store.peek_record(user.id)
            attempts = 0
            if (
                replay_pending_state is None
                and pending_msg
                and _is_role_scoped_pending_field(state)
                and _is_working_or_root_pending_field(state)
            ):
                pending_store.pop_record(user.id)
                pending_fields.delete(user.id)
                _clear_pending_replay_counters(context, user.id)
                await update.message.reply_text(
                    "Не удалось автоматически продолжить запрос. "
                    "Отправь исходный запрос в группу ещё раз."
                )
                return
            if replay_pending_state and _is_role_scoped_pending_field(state) and _is_same_pending_field_state(replay_pending_state, state):
                attempts = _increment_pending_replay_counter(context, user.id, state, replay_pending_msg)
            replay_plan = build_pending_field_replay_plan(
                state=state,
                replay_pending_state=replay_pending_state,
                pending_msg_exists=bool(pending_msg),
                replay_attempts=attempts,
                max_retries=_MAX_ROLE_SCOPED_REPLAY_PROMPT_RETRIES,
            )
            if replay_plan.action == "request_again":
                if _is_root_dir_pending_field(state):
                    logger.warning(
                        "root_dir_replay_failed user_id=%s team_id=%s role_id=%s attempt=%s",
                        user.id,
                        state.get("team_id"),
                        state.get("role_id"),
                        attempts,
                    )
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
            if replay_plan.action == "suppress_and_drop":
                if _is_root_dir_pending_field(state):
                    logger.warning(
                        "root_dir_prompt_repeated_suppressed user_id=%s team_id=%s role_id=%s attempts=%s",
                        user.id,
                        state.get("team_id"),
                        state.get("role_id"),
                        attempts,
                    )
                pending_store.pop_record(user.id)
                pending_fields.delete(user.id)
                _clear_pending_replay_counters(context, user.id)
                await update.message.reply_text(
                    "Не удалось автоматически продолжить после нескольких попыток. "
                    "Отправь запрос в группу ещё раз."
                )
                return
            if replay_plan.should_delete_saved_value:
                _delete_provider_user_field_from_pending_state(storage, state)
            if replay_plan.action == "noop":
                _clear_pending_replay_counters(context, user.id)
                return
            if replay_plan.action == "missing_pending_message":
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
                    provider_models = _resolve_provider_models(context)
                    provider_registry = _resolve_provider_registry(context)
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
                    with storage.transaction(immediate=True):
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
                with storage.transaction(immediate=True):
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
                with storage.transaction(immediate=True):
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
        pending: PendingStore = _resolve_pending_store(context)
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
    except Exception as exc:
        error_result = Result.fail_from_exception(
            exc,
            fallback_code=ErrorCode.INTERNAL_UNEXPECTED,
            fallback_message="Failed to process private message",
            fallback_details={
                "entity": "private_message",
                "cause": "handle_failed",
                "id": str(user.id),
                "correlation_id": correlation_id,
            },
        )
        log_structured_error(
            logger,
            event="private_message_failed",
            error=error_result.error,
            extra={"user_id": user.id},
        )
        await update.message.reply_text(
            to_telegram_message(error_result.error, "Не удалось обработать сообщение. Попробуйте позже.")
        )
        return


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
    storage: Storage = _resolve_storage(context)
    pending_prompts = _resolve_pending_prompts(context)
    pending_roles = _resolve_pending_role_ops(context)
    pending_msg = _resolve_pending_store(context).peek(user_id)
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
        with storage.transaction(immediate=True):
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
            with storage.transaction(immediate=True):
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
            with storage.transaction(immediate=True):
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
    correlation_id = _ensure_runtime_correlation_id()
    runtime_client = resolve_runtime_client(context.application.bot_data)
    return await runtime_client.process_pending_replay(
        context=context,
        user_id=user_id,
        correlation_id=correlation_id,
        clear_counters_fn=lambda uid: _clear_pending_replay_counters(context, uid),
        request_token_fn=_request_token_for_user,
    )
