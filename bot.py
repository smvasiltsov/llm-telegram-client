from __future__ import annotations

import asyncio
import logging
import html
import httpx
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram import BotCommand
from telegram import BotCommandScopeAllGroupChats, BotCommandScopeDefault, BotCommandScopeChat
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram import BotCommandScopeAllPrivateChats
from telegram.constants import ParseMode
from telegram.error import BadRequest
 
import re

from app.auth import AuthService
from app.config import load_config, load_dotenv
from app.llm_executor import LLMExecutor
from app.llm_router import LLMRouter, MissingUserField
from app.llm_providers import ProviderConfig, ProviderUserField, load_provider_registry, model_label
from app.message_buffer import MessageBuffer
from app.plugin_server import PluginServerConfig, PluginTextServer
from app.plugins import PluginManager, load_plugins
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.roles_registry import seed_group_roles, seed_roles
from app.router import route_message
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.storage import Storage
from app.tools import (
    BashTool,
    ToolAuthRequiredError,
    ToolContext,
    ToolMCPAdapter,
    ToolService,
    ToolTimeoutError,
    ToolValidationError,
)
from app.tools.registry import ToolRegistry
from app.utils import split_message


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")


def _provider_id_from_model(
    model_override: str | None,
    default_provider_id: str,
    provider_registry: dict[str, ProviderConfig],
) -> str:
    if not model_override:
        return default_provider_id
    if ":" in model_override:
        return model_override.split(":", 1)[0]
    if model_override in provider_registry:
        return model_override
    return default_provider_id


def _role_requires_auth(
    provider_registry: dict[str, ProviderConfig],
    model_override: str | None,
    default_provider_id: str,
) -> bool:
    provider_id = _provider_id_from_model(model_override, default_provider_id, provider_registry)
    provider = provider_registry.get(provider_id)
    if not provider:
        return True
    return provider.auth_mode != "none"


def _format_with_header(header: str | None, text: str) -> str:
    if not header:
        return html.escape(text)
    return f"<b>{html.escape(header)}</b>\n\n{html.escape(text)}"


def _format_with_header_raw(header: str | None, text: str) -> str:
    if not header:
        return text
    return f"<b>{html.escape(header)}</b>\n\n{text}"


def _markdown_to_html_simple(text: str) -> str:
    escaped = html.escape(text)

    codeblocks: list[str] = []

    def _codeblock_repl(match: re.Match[str]) -> str:
        codeblocks.append(match.group(1))
        return f"__CODEBLOCK_{len(codeblocks) - 1}__"

    escaped = re.sub(r"```(?:[^\n]*)\n?(.*?)```", _codeblock_repl, escaped, flags=re.S)

    inline_codes: list[str] = []

    def _inline_code_repl(match: re.Match[str]) -> str:
        inline_codes.append(match.group(1))
        return f"__INLINECODE_{len(inline_codes) - 1}__"

    escaped = re.sub(r"`([^`]+)`", _inline_code_repl, escaped)

    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
    escaped = re.sub(r"_(.+?)_", r"<i>\1</i>", escaped)

    for i, code in enumerate(inline_codes):
        escaped = escaped.replace(f"__INLINECODE_{i}__", f"<code>{code}</code>")

    for i, code in enumerate(codeblocks):
        escaped = escaped.replace(f"__CODEBLOCK_{i}__", f"<pre><code>{code}</code></pre>")

    return escaped


def _render_llm_text(text: str, formatting_mode: str, allow_raw_html: bool) -> str:
    if formatting_mode == "markdown":
        return text
    if not allow_raw_html:
        return html.escape(text)
    return _markdown_to_html_simple(text)


async def _send_formatted_with_fallback(
    bot: Any,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
    reply_markup: Any | None = None,
    allow_raw_html: bool = True,
    formatting_mode: str = "html",
) -> None:
    mode = formatting_mode.lower()
    if mode == "markdown":
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        except BadRequest:
            await bot.send_message(
                chat_id=chat_id,
                text=html.escape(text),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        return

    if not allow_raw_html:
        await bot.send_message(
            chat_id=chat_id,
            text=html.escape(text),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
        return

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )
    except BadRequest:
        await bot.send_message(
            chat_id=chat_id,
            text=html.escape(text),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
        )


def _build_plugin_reply_markup(
    reply_markup: Any | None,
    is_private: bool,
    logger: logging.Logger,
    log_ctx: dict[str, Any],
) -> Any | None:
    if not isinstance(reply_markup, dict) or reply_markup.get("type") != "web_app_button":
        return reply_markup

    button_text = str(reply_markup.get("text") or "Открыть полностью")
    url = str(reply_markup.get("url") or "")
    if not url:
        logger.info("plugin button skipped: empty url %s", log_ctx)
        return None
    if len(url) > 1000:
        logger.info("plugin button skipped: url too long len=%s %s", len(url), log_ctx)
        return None

    if is_private:
        logger.info("plugin button private web_app url_len=%s %s", len(url), log_ctx)
        return InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, web_app=WebAppInfo(url=url))]])

    logger.info("plugin button group url_len=%s %s", len(url), log_ctx)
    return InlineKeyboardMarkup([[InlineKeyboardButton(text=button_text, url=url)]])


async def handle_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
        return
    storage: Storage = context.application.bot_data["storage"]
    groups = storage.list_groups()
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
    if not update.message or not update.effective_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
        return
    if not context.args:
        await update.message.reply_text("Использование: /roles <group_id>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("group_id должен быть числом.")
        return
    storage: Storage = context.application.bot_data["storage"]
    roles = storage.list_roles_for_group(group_id)
    if not roles:
        await update.message.reply_text("Роли для группы не настроены.")
        return
    keyboard = [
        [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"role:{group_id}:{role.role_id}")]
        for role in roles
    ]
    keyboard.append([InlineKeyboardButton(text="➕ Добавить роль", callback_data=f"addrole:{group_id}")])
    await update.message.reply_text(
        f"Роли группы {group_id}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_role_set_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
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
    storage: Storage = context.application.bot_data["storage"]
    role = storage.get_role_by_name(role_name)
    storage.ensure_group_role(group_id, role.role_id)
    storage.set_group_role_prompt(group_id, role.role_id, prompt)
    await update.message.reply_text(f"Промпт роли @{role.role_name} для группы {group_id} обновлён.")


async def handle_role_reset_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
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
    storage: Storage = context.application.bot_data["storage"]
    role = storage.get_role_by_name(role_name)
    storage.delete_user_role_session(update.effective_user.id, group_id, role.role_id)
    provider_registry = context.application.bot_data["provider_registry"]
    default_provider_id = context.application.bot_data["default_provider_id"]
    group_role = storage.get_group_role(group_id, role.role_id)
    model_override = group_role.model_override or role.llm_model
    provider_id = _provider_id_from_model(model_override, default_provider_id, provider_registry)
    provider = provider_registry.get(provider_id)
    if provider:
        for field in provider.user_fields.values():
            if field.scope == "role":
                storage.delete_provider_user_value(provider_id, field.key, role.role_id)
    await update.message.reply_text(
        f"Сессия для роли @{role.role_name} в группе {group_id} сброшена. Новый чат будет создан при следующем запросе."
    )


async def handle_bash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.effective_chat:
        return
    if not bool(context.application.bot_data.get("tools_bash_enabled", False)):
        await update.message.reply_text("Инструмент /bash отключён в конфиге.")
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
        return

    text = update.message.text or ""
    cmd = text.split(" ", 1)[1].strip() if " " in text else ""
    if not cmd:
        await update.message.reply_text("Использование: /bash <команда>")
        return

    executed = await _execute_bash_command(
        cmd=cmd,
        caller_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        message_id=update.message.message_id,
        context=context,
        trusted=False,
    )
    if executed:
        return

    pending_bash_auth: dict[int, dict[str, Any]] = context.application.bot_data["pending_bash_auth"]
    pending_bash_auth[update.effective_user.id] = {
        "cmd": cmd,
        "chat_id": update.effective_chat.id,
        "message_id": update.message.message_id,
    }
    await _request_bash_password(update.effective_chat.id, context)


async def handle_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if update.effective_user.id != owner_user_id:
        return
    tool_service: ToolService = context.application.bot_data["tool_service"]
    tools = tool_service.list_tools()
    if not tools:
        await update.message.reply_text("Инструменты не настроены.")
        return
    safe_commands = context.application.bot_data.get("tools_bash_safe_commands", [])
    lines = ["Доступные инструменты:"]
    for item in tools:
        lines.append(f"- {item['name']}: {item['description']}")
    if safe_commands:
        lines.append("")
        lines.append("Safe bash commands:")
        lines.append(", ".join(str(cmd) for cmd in safe_commands))
    for chunk in split_message("\n".join(lines)):
        await update.message.reply_text(chunk)


async def _execute_bash_command(
    *,
    cmd: str,
    caller_id: int,
    chat_id: int,
    message_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    trusted: bool,
) -> bool:
    tool_service: ToolService = context.application.bot_data["tool_service"]
    storage: Storage = context.application.bot_data["storage"]
    bash_cwd_by_user: dict[int, str] = context.application.bot_data["bash_cwd_by_user"]
    tool_ctx = ToolContext(
        caller_id=caller_id,
        chat_id=chat_id,
        source="telegram",
        request_id=f"tg:{chat_id}:{message_id}",
    )
    tool_input: dict[str, Any] = {"cmd": cmd, "trusted": trusted}
    current_cwd = bash_cwd_by_user.get(caller_id)
    if current_cwd:
        tool_input["cwd"] = current_cwd
    try:
        result = await tool_service.execute("bash", tool_input, tool_ctx)
    except ToolAuthRequiredError:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role="privileged",
            requires_password=True,
            trusted=trusted,
            status="auth_required",
        )
        return False
    except ToolValidationError as exc:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="validation_error",
            error_text=str(exc),
        )
        await context.bot.send_message(chat_id=chat_id, text=f"Ошибка в параметрах: {exc}")
        return True
    except ToolTimeoutError as exc:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="timeout",
            error_text=str(exc),
        )
        await context.bot.send_message(chat_id=chat_id, text=f"Таймаут: {exc}")
        return True
    except Exception:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="error",
            error_text="unexpected_error",
        )
        logger.exception("bash tool failed")
        await context.bot.send_message(chat_id=chat_id, text="Ошибка выполнения команды.")
        return True

    result_cwd = result.meta.get("cwd")
    if isinstance(result_cwd, str) and result_cwd.strip():
        bash_cwd_by_user[caller_id] = result_cwd

    body = _render_bash_result(cmd, result)
    storage.log_tool_run(
        telegram_user_id=caller_id,
        chat_id=chat_id,
        source="telegram",
        tool_name="bash",
        command_text=cmd,
        role=str(result.meta.get("role") or ""),
        requires_password=bool(result.meta.get("requires_password", False)),
        trusted=trusted,
        status="ok" if result.ok else "non_zero_exit",
        exit_code=result.exit_code,
        duration_ms=int(result.meta.get("duration_ms", 0)),
    )
    for chunk in split_message(body):
        await context.bot.send_message(chat_id=chat_id, text=chunk)
    return True


def _render_bash_result(cmd: str, result: Any) -> str:
    duration_ms = result.meta.get("duration_ms")
    role = result.meta.get("role")
    cwd = result.meta.get("cwd")
    lines = [
        f"$ {cmd}",
        f"role: {role}",
        f"cwd: {cwd}",
        f"exit_code: {result.exit_code}",
        f"duration_ms: {duration_ms}",
    ]
    if result.meta.get("truncated_stdout"):
        lines.append("stdout: truncated")
    if result.meta.get("truncated_stderr"):
        lines.append("stderr: truncated")
    header = "\n".join(lines).strip()
    stdout = result.stdout.strip() or "<empty>"
    stderr = result.stderr.strip()
    body = f"{header}\n\nSTDOUT:\n{stdout}"
    if stderr:
        body = f"{body}\n\nSTDERR:\n{stderr}"
    return body


async def _request_bash_password(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=chat_id,
        text="Команда требует подтверждение. Введите пароль из .env (BASH_DANGEROUS_PASSWORD).",
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return
    owner_user_id = context.application.bot_data["owner_user_id"]
    if query.from_user.id != owner_user_id:
        await query.answer()
        return
    storage: Storage = context.application.bot_data["storage"]
    data = query.data or ""
    if not data.startswith("addrole_model:"):
        context.application.bot_data["pending_prompts"].pop(query.from_user.id, None)
        context.application.bot_data["pending_role_ops"].pop(query.from_user.id, None)
    if data.startswith("grp:"):
        group_id = int(data.split(":", 1)[1])
        roles = storage.list_roles_for_group(group_id)
        keyboard = [
            [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"role:{group_id}:{role.role_id}")]
            for role in roles
        ]
        keyboard.append([InlineKeyboardButton(text="➕ Добавить роль", callback_data=f"addrole:{group_id}")])
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back:groups")])
        await query.edit_message_text(
            f"Роли группы {group_id}:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data == "back:groups":
        groups = storage.list_groups()
        keyboard = [
            [InlineKeyboardButton(text=(group.title or "(без названия)"), callback_data=f"grp:{group.group_id}")]
            for group in groups
        ]
        await query.edit_message_text(
            "Выбери группу:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data.startswith("role:"):
        _, group_id_str, role_id_str = data.split(":", 2)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        role = storage.get_role_by_id(role_id)
        keyboard = [
            [InlineKeyboardButton(text="Системный промпт", callback_data=f"act:set_prompt:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Инструкция к сообщениям", callback_data=f"act:set_suffix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Инструкция для реплаев", callback_data=f"act:set_reply_prefix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="LLM-модель", callback_data=f"act:set_model:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Переименовать роль", callback_data=f"act:rename_role:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Сбросить сессию", callback_data=f"act:reset_session:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Удалить роль", callback_data=f"act:delete_role:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")],
        ]
        await query.edit_message_text(
            f"Роль @{role.role_name}. Выбери действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data.startswith("addrole:"):
        group_id = int(data.split(":", 1)[1])
        keyboard = [
            [InlineKeyboardButton(text="Скопировать роль", callback_data=f"addrole_copy:{group_id}")],
            [InlineKeyboardButton(text="Создать новую", callback_data=f"addrole_create:{group_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")],
        ]
        await query.edit_message_text(
            "Как добавить роль?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data.startswith("addrole_copy:"):
        target_group_id = int(data.split(":", 1)[1])
        groups = storage.list_groups()
        keyboard = [
            [InlineKeyboardButton(text=(group.title or str(group.group_id)), callback_data=f"addrole_srcgrp:{target_group_id}:{group.group_id}")]
            for group in groups
        ]
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole:{target_group_id}")])
        await query.edit_message_text(
            "Выбери группу-источник:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data.startswith("addrole_srcgrp:"):
        _, target_group_id_str, source_group_id_str = data.split(":", 2)
        target_group_id = int(target_group_id_str)
        source_group_id = int(source_group_id_str)
        roles = storage.list_roles_for_group(source_group_id)
        keyboard = [
            [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"addrole_srcrole:{target_group_id}:{source_group_id}:{role.role_id}")]
            for role in roles
        ]
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole_copy:{target_group_id}")])
        await query.edit_message_text(
            "Выбери роль для копирования:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return
    if data.startswith("addrole_srcrole:"):
        _, target_group_id_str, source_group_id_str, role_id_str = data.split(":", 3)
        target_group_id = int(target_group_id_str)
        source_group_id = int(source_group_id_str)
        role_id = int(role_id_str)
        pending_roles = context.application.bot_data["pending_role_ops"]
        pending_roles[query.from_user.id] = {
            "mode": "clone",
            "step": "name",
            "target_group_id": target_group_id,
            "source_group_id": source_group_id,
            "source_role_id": role_id,
        }
        role = storage.get_role_by_id(role_id)
        await query.edit_message_text(
            f"Отправь новое имя роли для копии @{role.role_name}.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole_copy:{target_group_id}")]]
            ),
        )
        await query.answer()
        return
    if data.startswith("addrole_create:"):
        group_id = int(data.split(":", 1)[1])
        pending_roles = context.application.bot_data["pending_role_ops"]
        pending_roles[query.from_user.id] = {
            "mode": "create",
            "step": "name",
            "target_group_id": group_id,
        }
        await query.edit_message_text(
            "Отправь имя новой роли (латиница, цифры, underscore).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole:{group_id}")]]
            ),
        )
        await query.answer()
        return
    if data.startswith("act:"):
        _, action, group_id_str, role_id_str = data.split(":", 3)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        role = storage.get_role_by_id(role_id)
        if action == "set_prompt":
            group_role = storage.get_group_role(group_id, role_id)
            if group_role.system_prompt_override is not None:
                prompt = group_role.system_prompt_override
            else:
                prompt = role.base_system_prompt
            if not prompt:
                prompt = "(не задано)"
            pending_prompts = context.application.bot_data["pending_prompts"]
            pending_prompts[query.from_user.id] = (group_id, role_id)
            await query.edit_message_text(
                "Ваш системный промпт сейчас такой:\n\n"
                f"{prompt}\n\n"
                "Хотите ввести новый? Напишите его следующим сообщением (или 'clear', чтобы удалить).",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_prompt:{group_id}:{role_id}")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                    ]
                ),
            )
            await query.answer()
            return
        if action == "clear_prompt":
            storage.set_group_role_prompt(group_id, role_id, "")
            await query.edit_message_text(
                "Системный промпт очищен.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return
        if action == "rename_role":
            pending_roles = context.application.bot_data["pending_role_ops"]
            pending_roles[query.from_user.id] = {
                "mode": "rename",
                "step": "name",
                "target_group_id": group_id,
                "role_id": role_id,
            }
            await query.edit_message_text(
                f"Отправь новое имя для роли @{role.role_name} (латиница, цифры, underscore).",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return
        if action == "set_model":
            group_role = storage.get_group_role(group_id, role_id)
            provider_models = context.application.bot_data["provider_models"]
            provider_model_map = context.application.bot_data["provider_model_map"]
            provider_registry = context.application.bot_data["provider_registry"]
            current_model = _resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                group_role.model_override,
            )
            current_model_label = current_model
            current_model_obj = provider_model_map.get(current_model)
            if current_model_obj:
                current_provider = provider_registry.get(current_model_obj.provider_id)
                current_model_label = model_label(current_model_obj, current_provider)
            if not provider_models:
                await query.edit_message_text(
                    "Список моделей не настроен в llm_providers.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                    ),
                )
                await query.answer()
                return
            buttons = []
            for model in provider_models:
                provider = provider_registry.get(model.provider_id)
                label = model_label(model, provider)
                buttons.append(
                    [InlineKeyboardButton(text=label, callback_data=f"setmodel:{group_id}:{role_id}:{model.full_id}")]
                )
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")])
            await query.edit_message_text(
                f"Текущая модель: {current_model_label}\n\nВыбери модель:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            await query.answer()
            return
        if action == "set_suffix":
            pending_roles = context.application.bot_data["pending_role_ops"]
            pending_roles[query.from_user.id] = {
                "mode": "suffix",
                "step": "suffix",
                "target_group_id": group_id,
                "role_id": role_id,
            }
            group_role = storage.get_group_role(group_id, role_id)
            current_suffix = group_role.user_prompt_suffix or "(не задано)"
            text = (
                "Эта инструкция будет добавляться перед каждым сообщением пользователя и уходить в LLM одним сообщением.\n\n"
                "Текущая инструкция к сообщениям:\n\n"
                f"{current_suffix}\n\n"
                "Хотите изменить? Отправьте новую инструкцию (или 'clear' чтобы убрать)."
            )
            chunks = list(split_message(text))
            await query.edit_message_text(
                chunks[0],
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_suffix:{group_id}:{role_id}")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                    ]
                ),
            )
            for extra in chunks[1:]:
                await context.bot.send_message(chat_id=query.message.chat.id, text=extra)
            await query.answer()
            return
        if action == "clear_suffix":
            storage.set_group_role_user_prompt_suffix(group_id, role_id, None)
            await query.edit_message_text(
                "Инструкция к сообщениям очищена.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return
        if action == "set_reply_prefix":
            pending_roles = context.application.bot_data["pending_role_ops"]
            pending_roles[query.from_user.id] = {
                "mode": "reply_prefix",
                "step": "reply_prefix",
                "target_group_id": group_id,
                "role_id": role_id,
            }
            group_role = storage.get_group_role(group_id, role_id)
            current_prefix = group_role.user_reply_prefix or "(не задано)"
            text = (
                "Эта инструкция будет добавляться перед текстом сообщения, на которое пользователь отвечает.\n\n"
                "Текущая инструкция для реплаев:\n\n"
                f"{current_prefix}\n\n"
                "Хотите изменить? Отправьте новую инструкцию (или 'clear' чтобы убрать)."
            )
            chunks = list(split_message(text))
            await query.edit_message_text(
                chunks[0],
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_reply_prefix:{group_id}:{role_id}")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                    ]
                ),
            )
            for extra in chunks[1:]:
                await context.bot.send_message(chat_id=query.message.chat.id, text=extra)
            await query.answer()
            return
        if action == "clear_reply_prefix":
            storage.set_group_role_user_reply_prefix(group_id, role_id, None)
            await query.edit_message_text(
                "Инструкция для реплаев очищена.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return
        if action == "reset_session":
            storage.delete_user_role_session(query.from_user.id, group_id, role_id)
            provider_registry = context.application.bot_data["provider_registry"]
            default_provider_id = context.application.bot_data["default_provider_id"]
            group_role = storage.get_group_role(group_id, role_id)
            model_override = group_role.model_override or role.llm_model
            provider_id = _provider_id_from_model(model_override, default_provider_id, provider_registry)
            provider = provider_registry.get(provider_id)
            if provider:
                for field in provider.user_fields.values():
                    if field.scope == "role":
                        storage.delete_provider_user_value(provider_id, field.key, role_id)
            await query.edit_message_text(
                f"Сессия для роли @{role.role_name} в группе {group_id} сброшена.",
            )
            await query.answer()
            return
        if action == "delete_role":
            storage.deactivate_group_role(group_id, role_id)
            storage.delete_user_role_session(query.from_user.id, group_id, role_id)
            storage.delete_role_if_unused(role_id)
            await query.edit_message_text(
                f"Роль @{role.role_name} удалена из группы {group_id}.",
            )
            await query.answer()
            return
    if data.startswith("setmodel:"):
        _, group_id_str, role_id_str, model_name = data.split(":", 3)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        provider_model_map = context.application.bot_data["provider_model_map"]
        if model_name not in provider_model_map:
            await query.edit_message_text(
                "Модель не найдена в llm_providers.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return
        storage.set_group_role_model(group_id, role_id, model_name)
        provider_registry = context.application.bot_data["provider_registry"]
        provider_model_map = context.application.bot_data["provider_model_map"]
        model_obj = provider_model_map.get(model_name)
        label = model_name
        if model_obj:
            provider = provider_registry.get(model_obj.provider_id)
            label = model_label(model_obj, provider)
        await query.edit_message_text(
            f"Модель для роли обновлена: {label}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return
    if data.startswith("addrole_model:"):
        model_name = data.split(":", 1)[1]
        pending_roles = context.application.bot_data["pending_role_ops"]
        state = pending_roles.get(query.from_user.id)
        if not state or state.get("step") != "model_select":
            await query.answer()
            return
        provider_model_map = context.application.bot_data["provider_model_map"]
        if model_name != "__skip__" and model_name not in provider_model_map:
            await query.edit_message_text(
                "Модель не найдена в llm_providers.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{state['target_group_id']}")]]
                ),
            )
            await query.answer()
            return
        model = None if model_name == "__skip__" else model_name
        target_group_id = state["target_group_id"]
        role_name = state["role_name"]
        prompt = state["prompt"]
        if state["mode"] == "create":
            role = storage.upsert_role(
                role_name=role_name,
                description=f"Роль {role_name}",
                base_system_prompt=prompt,
                extra_instruction="",
                llm_model=model,
                is_active=True,
            )
        else:
            source_role = storage.get_role_by_id(state["source_role_id"])
            role = storage.upsert_role(
                role_name=role_name,
                description=source_role.description,
                base_system_prompt=source_role.base_system_prompt,
                extra_instruction=source_role.extra_instruction,
                llm_model=source_role.llm_model,
                is_active=True,
            )
        storage.ensure_group_role(target_group_id, role.role_id)
        if model is not None:
            storage.set_group_role_model(target_group_id, role.role_id, model)
        pending_roles.pop(query.from_user.id, None)
        await query.edit_message_text(
            f"Роль @{role.role_name} добавлена в группу {target_group_id}.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{target_group_id}")]]
            ),
        )
        await query.answer()
        return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text
    user = update.effective_user
    if not user:
        return

    storage: Storage = context.application.bot_data["storage"]
    storage.upsert_user(user.id, user.username)

    bot_username = context.application.bot_data["bot_username"]
    roles = storage.list_roles_for_group(update.effective_chat.id)
    owner_user_id = context.application.bot_data["owner_user_id"]
    require_bot_mention = context.application.bot_data["require_bot_mention"]
    route = route_message(
        text,
        bot_username,
        roles,
        owner_user_id=owner_user_id,
        author_user_id=user.id,
        require_bot_mention=require_bot_mention,
    )
    if not route:
        return

    if not route.content:
        await update.message.reply_text("Напиши сообщение после роли.")
        return

    cipher: TokenCipher = context.application.bot_data["cipher"]
    auth = storage.get_auth_token(user.id)
    provider_registry = context.application.bot_data["provider_registry"]
    default_provider_id = context.application.bot_data["default_provider_id"]
    provider_models = context.application.bot_data["provider_models"]
    provider_model_map = context.application.bot_data["provider_model_map"]
    requires_auth = False
    for role in route.roles:
        group_role = storage.get_group_role(update.effective_chat.id, role.role_id)
        if provider_models:
            model_override = _resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                group_role.model_override or role.llm_model,
            )
        else:
            model_override = group_role.model_override or role.llm_model
        if _role_requires_auth(provider_registry, model_override, default_provider_id):
            requires_auth = True
            break

    if requires_auth and (not auth or not auth.is_authorized):
        pending: PendingStore = context.application.bot_data["pending_store"]
        if update.effective_chat and update.message:
            role_name = "__all__" if route.is_all else route.roles[0].role_name
            pending.save(
                telegram_user_id=user.id,
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
                role_name=role_name,
                content=route.content,
                reply_text=update.message.reply_to_message.text if update.message.reply_to_message else None,
            )
        await _request_token(update, context)
        return

    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    llm_executor: LLMExecutor = context.application.bot_data["llm_executor"]
    resolver: SessionResolver = context.application.bot_data["session_resolver"]

    provider_models = context.application.bot_data["provider_models"]
    provider_model_map = context.application.bot_data["provider_model_map"]
    for role in route.roles:
        try:
            group_role = storage.get_group_role(update.effective_chat.id, role.role_id)
            if provider_models:
                model_override = _resolve_provider_model(
                    provider_models,
                    provider_model_map,
                    provider_registry,
                    group_role.model_override or role.llm_model,
                )
            else:
                logger.warning("Provider model list is empty for role=%s", role.role_name)
                model_override = group_role.model_override or role.llm_model
            reply_text = update.message.reply_to_message.text if update.message.reply_to_message else None
            content = _build_llm_content(
                route.content,
                group_role.user_prompt_suffix,
                group_role.user_reply_prefix,
                reply_text,
            )
            session_id = await resolver.resolve(
                user.id,
                update.effective_chat.id,
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
                user.id,
                update.effective_chat.id,
                update.message.message_id,
                role_name,
                route.content,
                reply_text,
                exc,
                context,
            )
            return
        except Exception as exc:
            if _is_unauthorized(exc):
                pending: PendingStore = context.application.bot_data["pending_store"]
                role_name = "__all__" if route.is_all else route.roles[0].role_name
                pending.save(
                    user.id,
                    update.effective_chat.id,
                    update.message.message_id,
                    role_name,
                    route.content,
                    reply_text=update.message.reply_to_message.text if update.message.reply_to_message else None,
                )
                storage.set_user_authorized(user.id, False)
                await _request_token(update, context)
                return
            logger.exception("LLM request failed user_id=%s role=%s", user.id, role.role_name)
            await update.message.reply_text("Ошибка при запросе к LLM. Попробуй позже.")
            continue

        allow_raw_html = bool(context.application.bot_data.get("allow_raw_html", True))
        formatting_mode = str(context.application.bot_data.get("formatting_mode", "html"))
        plugin_manager: PluginManager = context.application.bot_data["plugin_manager"]
        payload = {
            "text": response_text,
            "parse_mode": formatting_mode,
            "reply_markup": None,
        }
        logger.info(
            "plugin pre user_id=%s role=%s provider=%s text_len=%s",
            user.id,
            role.role_name,
            llm_executor.provider_id_for_model(model_override),
            len(response_text),
        )
        ctx_payload = {
            "chat_id": update.effective_chat.id,
            "user_id": user.id,
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
            "plugin post user_id=%s role=%s text_len=%s reply_markup=%s",
            user.id,
            role.role_name,
            len(response_text),
            bool(reply_markup),
        )
        final_reply_markup = _build_plugin_reply_markup(
            reply_markup,
            update.effective_chat.type == "private",
            logger,
            {"user_id": user.id, "role": role.role_name},
        )

        rendered = _render_llm_text(response_text, formatting_mode, allow_raw_html)
        full_text = _format_with_header_raw(None, rendered)
        for idx, chunk in enumerate(split_message(full_text)):
            await _send_formatted_with_fallback(
                context.bot,
                update.effective_chat.id,
                chunk,
                reply_to_message_id=update.message.message_id,
                reply_markup=final_reply_markup if idx == 0 else None,
                allow_raw_html=allow_raw_html,
                formatting_mode=formatting_mode,
            )


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        return
    storage: Storage = context.application.bot_data["storage"]
    user = update.effective_user
    if not user:
        return
    logger.info("private msg user_id=%s text=%r", user.id, update.message.text)
    storage.upsert_user(user.id, user.username)
    pending_bash_auth: dict[int, dict[str, Any]] = context.application.bot_data["pending_bash_auth"]
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
        expected_password = str(context.application.bot_data.get("tools_bash_password", "")).strip()
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
        await _execute_bash_command(
            cmd=pending_cmd,
            caller_id=user.id,
            chat_id=pending_chat_id,
            message_id=int(pending_bash["message_id"]),
            context=context,
            trusted=True,
        )
        return

    pending_prompts = context.application.bot_data["pending_prompts"]
    pending_roles = context.application.bot_data["pending_role_ops"]
    pending_fields: PendingUserFieldStore = context.application.bot_data["pending_user_fields"]
    pending_field_state = pending_fields.get(user.id)
    logger.info(
        "private pending state user_id=%s pending_field=%s pending_msg=%s",
        user.id,
        bool(pending_field_state),
        bool(context.application.bot_data["pending_store"].peek(user.id)),
    )
    if (
        update.message.text.strip().startswith("/")
        and not pending_field_state
        and user.id not in pending_prompts
        and user.id not in pending_roles
    ):
        return
    pending_msg = context.application.bot_data["pending_store"].peek(user.id)
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
        pending_msg = context.application.bot_data["pending_store"].peek(user.id)
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
        private_buffer: MessageBuffer = context.application.bot_data["private_buffer"]
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
            private_buffer: MessageBuffer = context.application.bot_data["private_buffer"]
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
            provider_models = context.application.bot_data["provider_models"]
            provider_registry = context.application.bot_data["provider_registry"]
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

    auth_service: AuthService = context.application.bot_data["auth_service"]
    pending: PendingStore = context.application.bot_data["pending_store"]
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
    storage: Storage = context.application.bot_data["storage"]
    storage.upsert_group(chat.id, chat.title)
    seed_group_roles(storage, chat.id)
    owner_user_id = context.application.bot_data["owner_user_id"]
    logger.info(
        "group msg owner_user_id=%s matched=%s",
        owner_user_id,
        update.effective_user.id == owner_user_id,
    )
    if update.effective_user.id != owner_user_id:
        return

    bot_username = context.application.bot_data["bot_username"]
    text = update.message.text
    require_bot_mention = context.application.bot_data["require_bot_mention"]
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

    buffer: MessageBuffer = context.application.bot_data["message_buffer"]
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
    buffer: MessageBuffer = context.application.bot_data["message_buffer"]
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

    bot_username = context.application.bot_data["bot_username"]
    storage: Storage = context.application.bot_data["storage"]
    roles = storage.list_roles_for_group(chat_id)
    owner_user_id = context.application.bot_data["owner_user_id"]
    require_bot_mention = context.application.bot_data["require_bot_mention"]
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
    provider_registry = context.application.bot_data["provider_registry"]
    default_provider_id = context.application.bot_data["default_provider_id"]
    provider_models = context.application.bot_data["provider_models"]
    provider_model_map = context.application.bot_data["provider_model_map"]
    requires_auth = False
    for role in route.roles:
        group_role = storage.get_group_role(chat_id, role.role_id)
        if provider_models:
            model_override = _resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                group_role.model_override or role.llm_model,
            )
        else:
            model_override = group_role.model_override or role.llm_model
        if _role_requires_auth(provider_registry, model_override, default_provider_id):
            requires_auth = True
            break

    if requires_auth and (not auth or not auth.is_authorized):
        pending: PendingStore = context.application.bot_data["pending_store"]
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

    cipher: TokenCipher = context.application.bot_data["cipher"]
    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    llm_executor: LLMExecutor = context.application.bot_data["llm_executor"]
    resolver: SessionResolver = context.application.bot_data["session_resolver"]

    provider_models = context.application.bot_data["provider_models"]
    provider_model_map = context.application.bot_data["provider_model_map"]
    reply_to_message_id = items[0].message_id
    for role in route.roles:
        try:
            group_role = storage.get_group_role(chat_id, role.role_id)
            if provider_models:
                model_override = _resolve_provider_model(
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
            content = _build_llm_content(
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
                pending: PendingStore = context.application.bot_data["pending_store"]
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
        allow_raw_html = bool(context.application.bot_data.get("allow_raw_html", True))
        formatting_mode = str(context.application.bot_data.get("formatting_mode", "html"))
        plugin_manager: PluginManager = context.application.bot_data["plugin_manager"]
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
        final_reply_markup = _build_plugin_reply_markup(
            reply_markup,
            chat_id > 0,
            logger,
            {"user_id": user_id, "role": role.role_name},
        )
        rendered = _render_llm_text(response_text, formatting_mode, allow_raw_html)
        full_text = _format_with_header_raw(None, rendered)
        for idx, chunk in enumerate(split_message(full_text)):
            await _send_formatted_with_fallback(
                context.bot,
                chat_id,
                chunk,
                reply_to_message_id=reply_to_message_id,
                reply_markup=final_reply_markup if idx == 0 else None,
                allow_raw_html=allow_raw_html,
                formatting_mode=formatting_mode,
            )


async def _flush_private_buffered(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    private_buffer: MessageBuffer = context.application.bot_data["private_buffer"]
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
    storage: Storage = context.application.bot_data["storage"]
    pending_prompts = context.application.bot_data["pending_prompts"]
    pending_roles = context.application.bot_data["pending_role_ops"]
    pending_msg = context.application.bot_data["pending_store"].peek(user_id)
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


async def _request_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text="Пришли, пожалуйста, авторизационный токен для LLM.",
        )
    except Exception:
        logger.exception("Failed to send DM token request user_id=%s", user.id)
        await update.message.reply_text("Не смог написать в личку. Напиши мне в личные сообщения.")


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
    pending: PendingStore = context.application.bot_data["pending_store"]
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
    pending_fields: PendingUserFieldStore = context.application.bot_data["pending_user_fields"]
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


async def _process_pending_message_for_user(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    pending: PendingStore = context.application.bot_data["pending_store"]
    pending_msg = pending.peek(user_id)
    if not pending_msg:
        logger.info("pending message not found user_id=%s", user_id)
        return False
    chat_id, message_id, role_name, content, reply_text = pending_msg
    storage: Storage = context.application.bot_data["storage"]
    roles = storage.list_roles_for_group(chat_id)
    if role_name == "__all__":
        target_roles = roles
    else:
        role = next((r for r in roles if r.role_name == role_name), None)
        if not role:
            logger.info("pending role not found user_id=%s role_name=%s", user_id, role_name)
            return False
        target_roles = [role]

    provider_registry = context.application.bot_data["provider_registry"]
    default_provider_id = context.application.bot_data["default_provider_id"]
    provider_models = context.application.bot_data["provider_models"]
    provider_model_map = context.application.bot_data["provider_model_map"]
    auth = storage.get_auth_token(user_id)
    requires_auth = False
    for role in target_roles:
        group_role = storage.get_group_role(chat_id, role.role_id)
        if provider_models:
            model_override = _resolve_provider_model(
                provider_models,
                provider_model_map,
                provider_registry,
                group_role.model_override or role.llm_model,
            )
        else:
            model_override = group_role.model_override or role.llm_model
        if _role_requires_auth(provider_registry, model_override, default_provider_id):
            requires_auth = True
            break
    if requires_auth and (not auth or not auth.is_authorized):
        await _request_token_for_user(chat_id, user_id, context)
        return False

    cipher: TokenCipher = context.application.bot_data["cipher"]
    session_token = cipher.decrypt(auth.encrypted_token) if auth and auth.encrypted_token else ""
    llm_executor: LLMExecutor = context.application.bot_data["llm_executor"]
    resolver: SessionResolver = context.application.bot_data["session_resolver"]

    had_error = False
    for role in target_roles:
        try:
            group_role = storage.get_group_role(chat_id, role.role_id)
            if provider_models:
                model_override = _resolve_provider_model(
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
            content_with_context = _build_llm_content(
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

        full_text = _format_with_header(None, response_text)
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


def _is_unauthorized(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    return response is not None and response.status_code == 401


async def handle_bot_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.my_chat_member or not update.effective_chat:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return
    new_status = update.my_chat_member.new_chat_member.status
    old_status = update.my_chat_member.old_chat_member.status
    storage: Storage = context.application.bot_data["storage"]
    if new_status in ("member", "administrator") and old_status in ("left", "kicked"):
        storage.upsert_group(chat.id, chat.title)
        seed_group_roles(storage, chat.id)
    elif new_status in ("left", "kicked"):
        storage.set_group_active(chat.id, False)


async def handle_group_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return
    logger.info("group seen chat_id=%s title=%r", chat.id, chat.title)
    storage: Storage = context.application.bot_data["storage"]
    storage.upsert_group(chat.id, chat.title)
    seed_group_roles(storage, chat.id)


def _resolve_provider_model(
    provider_models: list,
    provider_model_map: dict[str, Any],
    provider_registry: dict[str, ProviderConfig],
    selected_model: str | None,
) -> str:
    if selected_model and selected_model in provider_model_map:
        return selected_model
    if selected_model and selected_model in provider_registry:
        return selected_model
    if selected_model:
        logger.warning("Provider model override not found in registry model=%s", selected_model)
    if not provider_models:
        raise ValueError("No provider models loaded")
    return provider_models[0].full_id


def _build_llm_content(
    user_text: str,
    user_prompt_suffix: str | None,
    user_reply_prefix: str | None,
    reply_text: str | None,
) -> str:
    has_general = bool(user_prompt_suffix)
    has_reply = bool(reply_text)
    has_context_instr = bool(user_reply_prefix)
    if not has_general and not has_reply and not has_context_instr:
        return user_text

    parts: list[str] = []
    if has_general:
        parts.append("#GENERAL_INSTRUCTIONS")
        parts.append(user_prompt_suffix or "")
    if has_reply or has_context_instr:
        parts.append("#CONTEXT_INSTRUCTIONS")
        if user_reply_prefix:
            parts.append(user_reply_prefix)
        if reply_text:
            parts.append("#CONTEXT")
            parts.append(reply_text)
    parts.append("#USER_REQUEST")
    parts.append(user_text)
    return "\n\n".join(part for part in parts if part).strip()


async def main() -> None:
    config_path = Path(__file__).with_name("config.json")
    config = load_config(config_path)
    env_values = load_dotenv(Path(__file__).with_name(".env"))
    tools_bash_password = env_values.get("BASH_DANGEROUS_PASSWORD", "").strip()

    providers_dir = Path(__file__).with_name("llm_providers")
    provider_registry, provider_models = load_provider_registry(providers_dir)
    if not provider_models:
        raise ValueError("No provider models found in llm_providers")

    llm_clients: dict[str, httpx.AsyncClient] = {}
    for provider in provider_registry.values():
        verify = provider.tls_ca_cert_path or True
        llm_clients[provider.provider_id] = httpx.AsyncClient(
            base_url=provider.base_url.rstrip("/"),
            timeout=config.llm_timeout_sec,
            verify=verify,
        )

    if not llm_clients:
        raise ValueError("No providers configured in llm_providers")

    storage = Storage(config.database_path)
    seed_roles(storage)

    cipher = TokenCipher(config.encryption_key)
    default_provider_id = next(iter(llm_clients.keys()))
    llm_router = LLMRouter(provider_registry, llm_clients, storage, default_provider_id=default_provider_id)
    llm_executor = LLMExecutor(llm_router)
    session_resolver = SessionResolver(storage, llm_router)

    application = ApplicationBuilder().token(config.telegram_bot_token).build()
    me = await application.bot.get_me()

    pending_store = PendingStore(config.database_path)
    pending_user_fields = PendingUserFieldStore(config.database_path)
    pending_store.clear_all()
    pending_user_fields.clear_all()
    message_buffer = MessageBuffer(window_seconds=2.0)
    private_buffer = MessageBuffer(window_seconds=2.0)
    auth_service = AuthService(
        storage,
        cipher,
        llm_router,
        session_resolver,
        provider_registry,
        default_provider_id,
    )
    tool_registry = ToolRegistry()
    tools_bash_enabled = bool(config.tools_enabled and config.tools_bash_enabled)
    if tools_bash_enabled:
        if not tools_bash_password:
            logger.warning("BASH_DANGEROUS_PASSWORD is empty; privileged bash commands will be blocked")
        default_cwd = Path(config.tools_bash_default_cwd).expanduser()
        if not default_cwd.is_absolute():
            default_cwd = (Path.cwd() / default_cwd).resolve()
        else:
            default_cwd = default_cwd.resolve()
        allowed_workdirs = []
        for item in config.tools_bash_allowed_workdirs:
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            else:
                path = path.resolve()
            allowed_workdirs.append(path)
        tool_registry.register(
            BashTool(
                default_cwd=default_cwd,
                max_timeout_sec=config.tools_bash_max_timeout_sec,
                max_output_chars=config.tools_bash_max_output_chars,
                safe_commands=config.tools_bash_safe_commands,
                allowed_workdirs=allowed_workdirs or [default_cwd],
            )
        )
    tool_service = ToolService(tool_registry)
    tool_mcp_adapter = ToolMCPAdapter(tool_service)
    plugin_manager = load_plugins(Path("plugins"))
    plugin_server = PluginTextServer(
        storage,
        PluginServerConfig(
            host=config.plugin_server_host,
            port=config.plugin_server_port,
            enabled=config.plugin_server_enabled,
        ),
    )
    plugin_server.start()
    storage.reset_authorizations()
    application.bot_data.update(
        {
            "bot_username": me.username,
            "storage": storage,
            "cipher": cipher,
            "llm_router": llm_router,
            "llm_executor": llm_executor,
            "session_resolver": session_resolver,
            "pending_store": pending_store,
            "message_buffer": message_buffer,
            "private_buffer": private_buffer,
            "auth_service": auth_service,
            "owner_user_id": config.owner_user_id,
            "require_bot_mention": config.require_bot_mention,
            "pending_prompts": {},
            "pending_role_ops": {},
            "pending_user_fields": pending_user_fields,
            "provider_registry": provider_registry,
            "provider_models": provider_models,
            "provider_model_map": {m.full_id: m for m in provider_models},
            "default_provider_id": default_provider_id,
            "allow_raw_html": config.allow_raw_html,
            "formatting_mode": config.formatting_mode,
            "plugin_manager": plugin_manager,
            "plugin_server": plugin_server,
            "tool_service": tool_service,
            "tools_bash_enabled": tools_bash_enabled,
            "tools_bash_password": tools_bash_password,
            "tools_bash_safe_commands": list(config.tools_bash_safe_commands),
            "pending_bash_auth": {},
            "bash_cwd_by_user": {},
            "tool_mcp_adapter": tool_mcp_adapter,
        }
    )

    application.add_handler(CommandHandler("groups", handle_groups, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("tools", handle_tools, filters=filters.ChatType.PRIVATE))
    if tools_bash_enabled:
        application.add_handler(CommandHandler("bash", handle_bash, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("roles", handle_group_roles, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_set_prompt", handle_role_set_prompt, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_reset_session", handle_role_reset_session, filters=filters.ChatType.PRIVATE))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(ChatMemberHandler(handle_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, handle_group_seen), group=0)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private_message), group=1)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_group_buffered), group=1)

    try:
        await application.initialize()
        owner_commands = [
            BotCommand("groups", "Список групп и выбор"),
            BotCommand("tools", "Список инструментов"),
        ]
        if tools_bash_enabled:
            owner_commands.append(BotCommand("bash", "Выполнить bash команду"))
        await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=config.owner_user_id))
        await application.bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
        await application.bot.set_my_commands([], scope=BotCommandScopeAllGroupChats())
        await application.bot.set_my_commands([], scope=BotCommandScopeDefault())
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Release bot started as @%s", me.username)
        await asyncio.Event().wait()
    finally:
        plugin_server.stop()
        for client in llm_clients.values():
            await client.aclose()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
