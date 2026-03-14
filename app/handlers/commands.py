from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.runtime import RuntimeContext
from app.services.prompt_builder import provider_id_from_model
from app.services.tool_exec import execute_bash_command
from app.storage import Storage
from app.tools import ToolService
from app.utils import split_message

logger = logging.getLogger("bot")


def _list_telegram_groups(storage: Storage) -> list[tuple[int, str | None, int]]:
    result: list[tuple[int, str | None, int]] = []
    for binding in storage.list_team_bindings(interface_type="telegram", active_only=True):
        try:
            group_id = int(binding.external_id)
        except Exception:
            continue
        result.append((group_id, binding.external_title, binding.team_id))
    result.sort(key=lambda item: item[0])
    return result


async def handle_roles_master(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if update.effective_user.id != runtime.owner_user_id:
        return
    storage: Storage = runtime.storage
    roles = storage.list_active_roles()
    keyboard = [
        [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"mrole:{role.role_id}")]
        for role in roles
    ]
    keyboard.insert(0, [InlineKeyboardButton(text="➕ Создать master-role", callback_data="mrole_create")])
    await update.message.reply_text(
        "Выбери master-role:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if update.effective_user.id != runtime.owner_user_id:
        return
    storage: Storage = runtime.storage
    groups = _list_telegram_groups(storage)
    if not groups:
        await update.message.reply_text("Бот пока не добавлен ни в одну группу.")
        return
    keyboard = [
        [InlineKeyboardButton(text=(title or "(без названия)"), callback_data=f"grp:{group_id}")]
        for group in groups
        for group_id, title, _team_id in [group]
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
    if update.effective_user.id != runtime.owner_user_id:
        return
    if not context.args:
        await update.message.reply_text("Использование: /roles <group_id>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("group_id должен быть числом.")
        return
    storage: Storage = runtime.storage
    team_id = storage.resolve_team_id_by_telegram_chat(group_id)
    if team_id is None:
        await update.message.reply_text("Группа не найдена.")
        return
    group_roles = storage.list_team_roles(team_id)
    if not group_roles:
        await update.message.reply_text("Роли для группы не настроены.")
        return
    keyboard = []
    for group_role in group_roles:
        role = storage.get_role_by_id(group_role.role_id)
        status = "ON" if group_role.enabled else "OFF"
        mode = "ORCH" if group_role.mode == "orchestrator" else "ROLE"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"@{storage.get_team_role_name(team_id, role.role_id)} [{status}|{mode}]",
                    callback_data=f"role:{group_id}:{role.role_id}",
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
    if update.effective_user.id != runtime.owner_user_id:
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
    storage: Storage = runtime.storage
    team_id = storage.resolve_team_id_by_telegram_chat(group_id)
    if team_id is None:
        await update.message.reply_text("Группа не найдена.")
        return
    role = storage.get_role_for_team_by_name(team_id, role_name)
    storage.ensure_team_role(team_id, role.role_id)
    storage.set_team_role_prompt(team_id, role.role_id, prompt)
    await update.message.reply_text(
        f"Промпт роли @{storage.get_team_role_name(team_id, role.role_id)} для группы {group_id} обновлён."
    )


async def handle_role_reset_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if update.effective_user.id != runtime.owner_user_id:
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
    storage: Storage = runtime.storage
    team_id = storage.resolve_team_id_by_telegram_chat(group_id)
    if team_id is None:
        await update.message.reply_text("Группа не найдена.")
        return
    role = storage.get_role_for_team_by_name(team_id, role_name)
    team_role_id = storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True)
    if team_role_id is not None:
        storage.delete_user_role_session_by_team_role(update.effective_user.id, team_role_id)
    provider_registry = runtime.provider_registry
    default_provider_id = runtime.default_provider_id
    group_role = storage.get_team_role(team_id, role.role_id)
    model_override = group_role.model_override or role.llm_model
    provider_id = provider_id_from_model(model_override, default_provider_id, provider_registry)
    provider = provider_registry.get(provider_id)
    if provider:
        for field in provider.user_fields.values():
            if field.scope == "role":
                storage.delete_provider_user_value(provider_id, field.key, role.role_id)
    await update.message.reply_text(
        f"Сессия для роли @{storage.get_team_role_name(team_id, role.role_id)} в группе {group_id} сброшена. "
        "Новый чат будет создан при следующем запросе."
    )


async def handle_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if update.effective_user.id != runtime.owner_user_id:
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
    if update.effective_user.id != runtime.owner_user_id:
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
