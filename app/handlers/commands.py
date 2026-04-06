from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.application.contracts import AppError, log_structured_error, map_exception_to_error
from app.application.authz import (
    action_for_private_owner_command,
    actor_from_update,
    resource_ctx_from_update,
)
from app.application.use_cases.role_admin_view import (
    build_master_roles_view,
    build_team_roles_view,
)
from app.core.use_cases import (
    list_telegram_groups,
    reset_team_role_session,
    resolve_team_id,
)
from app.runtime import RuntimeContext
from app.services.tool_exec import execute_bash_command
from app.tools import ToolService
from app.utils import split_message

logger = logging.getLogger("bot")


def _map_value_error(exc: ValueError) -> AppError:
    code, message, details, http_status, retryable = map_exception_to_error(exc)
    return AppError(code=code, message=message, details=details, http_status=http_status, retryable=retryable)


def _is_owner_authorized(update: Update, runtime: RuntimeContext) -> bool:
    actor = actor_from_update(update)
    if actor is None:
        return False
    authz_service = getattr(runtime, "authz_service", None)
    if authz_service is None:
        return int(actor.user_id) == int(getattr(runtime, "owner_user_id", -1))
    result = authz_service.authorize(
        action=action_for_private_owner_command(),
        actor=actor,
        resource_ctx=resource_ctx_from_update(update),
    )
    if result.is_error:
        return False
    return bool(result.value and result.value.allowed)


async def handle_roles_master(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    view_result = build_master_roles_view(runtime=runtime, storage=runtime.storage)
    if view_result.is_error or view_result.value is None:
        log_structured_error(
            logger,
            event="commands_roles_master_failed",
            error=view_result.error,
            extra={"user_id": update.effective_user.id},
        )
        await update.message.reply_text("Не удалось загрузить список master-role.")
        return
    view = view_result.value
    keyboard = [
        [InlineKeyboardButton(text=f"@{role_name}", callback_data=f"mrole_name:{role_name}")]
        for role_name in view.role_names
    ]
    keyboard.insert(0, [InlineKeyboardButton(text="➕ Создать master-role", callback_data="mrole_create")])
    await update.message.reply_text(
        view.text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    groups = list_telegram_groups(runtime.storage)
    if not groups:
        await update.message.reply_text("Бот пока не добавлен ни в одну группу.")
        return
    keyboard = [
        [InlineKeyboardButton(text=(group.title or "(без названия)"), callback_data=f"grp:{group.group_id}")]
        for group in groups
    ]
    await update.message.reply_text(
        "Выбери группу:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_group_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    if not context.args:
        await update.message.reply_text("Использование: /roles <group_id>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("group_id должен быть числом.")
        return
    view_result = build_team_roles_view(storage=runtime.storage, group_id=group_id)
    if view_result.is_error or view_result.value is None:
        app_error = view_result.error
        if app_error is None:
            app_error = AppError(code="storage.not_found", message="Group not found", http_status=404, retryable=False)
        log_structured_error(
            logger,
            event="commands_group_roles_failed",
            error=app_error,
            extra={"group_id": group_id, "user_id": update.effective_user.id},
        )
        await update.message.reply_text("Группа не найдена.")
        return
    group_roles = view_result.value.roles
    if not group_roles:
        await update.message.reply_text("Роли для группы не настроены.")
        return
    keyboard = []
    for group_role in group_roles:
        status = "ON" if group_role.enabled else "OFF"
        mode = "ORCH" if group_role.mode == "orchestrator" else "ROLE"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"@{group_role.public_name} [{status}|{mode}]",
                    callback_data=f"role:{group_id}:{group_role.role_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(text="➕ Добавить роль", callback_data=f"addrole:{group_id}")])
    await update.message.reply_text(
        f"Роли группы {group_id}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_role_set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    if len(context.args) < 3:
        await update.message.reply_text("Использование: /role_set_prompt <group_id> <role> <prompt>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("group_id должен быть числом.")
        return
    role_name = context.args[1].lstrip("@")
    prompt = " ".join(context.args[2:]).strip()
    if not prompt:
        await update.message.reply_text("Prompt не может быть пустым.")
        return
    try:
        team_id = resolve_team_id(runtime.storage, group_id)
    except ValueError as exc:
        app_error = _map_value_error(exc)
        log_structured_error(
            logger,
            event="commands_role_set_prompt_resolve_team_failed",
            error=app_error,
            extra={"group_id": group_id, "user_id": update.effective_user.id},
        )
        await update.message.reply_text("Группа не найдена.")
        return
    role = runtime.storage.get_role_for_team_by_name(team_id, role_name)
    runtime.storage.ensure_team_role(team_id, role.role_id)
    runtime.storage.set_team_role_prompt(team_id, role.role_id, prompt)
    await update.message.reply_text(
        f"Промпт роли @{runtime.storage.get_team_role_name(team_id, role.role_id)} для группы {group_id} обновлён."
    )


async def handle_role_reset_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /role_reset_session <group_id> <role>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("group_id должен быть числом.")
        return
    role_name = context.args[1].lstrip("@")
    try:
        team_id = resolve_team_id(runtime.storage, group_id)
    except ValueError as exc:
        app_error = _map_value_error(exc)
        log_structured_error(
            logger,
            event="commands_role_reset_session_resolve_team_failed",
            error=app_error,
            extra={"group_id": group_id, "user_id": update.effective_user.id},
        )
        await update.message.reply_text("Группа не найдена.")
        return
    role = runtime.storage.get_role_for_team_by_name(team_id, role_name)
    public_name = reset_team_role_session(
        runtime,
        runtime.storage,
        group_id=group_id,
        role_id=role.role_id,
        user_id=update.effective_user.id,
    )
    await update.message.reply_text(
        f"Сессия для роли @{public_name} в группе {group_id} сброшена. "
        "Новый чат будет создан при следующем запросе."
    )


async def handle_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not _is_owner_authorized(update, runtime):
        return
    tool_service: ToolService = runtime.tool_service
    tools = tool_service.list_tools()
    if not tools:
        await update.message.reply_text("Инструменты не настроены.")
        return
    safe_commands = runtime.tools_bash_safe_commands
    lines = ["Доступные инструменты:"]
    for item in tools:
        lines.append(f"- {item['name']}: {item['description']}")
    if safe_commands:
        lines.append("")
        lines.append("Safe bash commands:")
        lines.append(", ".join(str(cmd) for cmd in safe_commands))
    for chunk in split_message("\n".join(lines)):
        await update.message.reply_text(chunk)


async def handle_bash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not runtime.tools_bash_enabled:
        await update.message.reply_text("Инструмент /bash отключён в конфиге.")
        return
    if not _is_owner_authorized(update, runtime):
        return

    text = update.message.text or ""
    cmd = text.split(" ", 1)[1].strip() if " " in text else ""
    if not cmd:
        await update.message.reply_text("Использование: /bash <команда>")
        return

    executed = await execute_bash_command(
        cmd=cmd,
        caller_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id,
        trusted=False,
        tool_service=runtime.tool_service,
        storage=runtime.storage,
        bash_cwd_by_user=runtime.bash_cwd_by_user,
        bot=context.bot,
    )
    if executed:
        return

    pending_bash_auth: dict[int, dict[str, Any]] = runtime.pending_bash_auth
    pending_bash_auth[update.effective_user.id] = {
        "cmd": cmd,
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
    }
    await _request_bash_password(update.effective_chat.id, context)

async def _request_bash_password(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text="Команда требует подтверждение. Введите пароль из .env (BASH_DANGEROUS_PASSWORD).",
    )
