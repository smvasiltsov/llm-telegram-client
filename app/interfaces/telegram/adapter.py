from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from telegram import BotCommand, Update
from telegram import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat, BotCommandScopeDefault
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.application.authz import AuthzActor, action_for_bootstrap_admin
from app.core.contracts.interface_io import CorePort
from app.core.errors.interface import InterfaceConfigError
from app.handlers.callbacks import handle_callback as cb_handle_callback
from app.handlers.commands import (
    handle_bash as cmd_handle_bash,
)
from app.handlers.commands import (
    handle_group_roles as cmd_handle_group_roles,
    handle_groups as cmd_handle_groups,
    handle_roles_master as cmd_handle_roles_master,
    handle_role_reset_session as cmd_handle_role_reset_session,
    handle_role_set_prompt as cmd_handle_role_set_prompt,
    handle_tools as cmd_handle_tools,
)
from app.handlers.membership import (
    handle_bot_membership as member_handle_bot_membership,
    handle_group_seen as member_handle_group_seen,
)
from app.handlers.messages_group import handle_group_buffered as msg_handle_group_buffered
from app.handlers.messages_private import handle_private_message as msg_handle_private_message
from app.interfaces.telegram_runtime_client import build_runtime_client
from app.runtime import RuntimeContext
from app.services.group_reconcile import (
    apply_reconcile_active_groups_writes,
    build_reconcile_active_groups_plan,
)


logger = logging.getLogger("bot")
HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def _resolve_storage(runtime: RuntimeContext):
    provider = getattr(runtime, "dependency_provider", None)
    if provider is not None:
        result = provider.storage_uow()
        if result.is_ok and result.value is not None:
            return result.value.storage
    return runtime.storage


def _resolve_tools_bash_enabled(runtime: RuntimeContext) -> bool:
    provider = getattr(runtime, "dependency_provider", None)
    if provider is not None:
        result = provider.tooling()
        if result.is_ok and result.value is not None:
            return bool(result.value.tools_bash_enabled)
    return bool(runtime.tools_bash_enabled)


def _resolve_tools_bash_password(runtime: RuntimeContext) -> str:
    provider = getattr(runtime, "dependency_provider", None)
    if provider is not None:
        result = provider.tooling()
        if result.is_ok and result.value is not None:
            return str(result.value.tools_bash_password)
    return str(runtime.tools_bash_password)


def register_handlers(
    application: Application,
    *,
    tools_bash_enabled: bool,
    private_message_handler: HandlerFn,
    group_buffered_handler: HandlerFn,
) -> None:
    application.add_handler(CommandHandler("groups", cmd_handle_groups, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("roles", cmd_handle_roles_master, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("tools", cmd_handle_tools, filters=filters.ChatType.PRIVATE))
    if tools_bash_enabled:
        application.add_handler(CommandHandler("bash", cmd_handle_bash, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("group_roles", cmd_handle_group_roles, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_set_prompt", cmd_handle_role_set_prompt, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_reset_session", cmd_handle_role_reset_session, filters=filters.ChatType.PRIVATE))
    application.add_handler(CallbackQueryHandler(cb_handle_callback))
    application.add_handler(ChatMemberHandler(member_handle_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, member_handle_group_seen), group=0)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, private_message_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), group_buffered_handler), group=1)


def build_telegram_application(token: str, runtime: RuntimeContext) -> Application:
    application = ApplicationBuilder().token(token).build()
    application.bot_data.update(runtime.to_bot_data())
    application.bot_data["runtime_client"] = build_runtime_client(
        thin_enabled=bool(getattr(runtime, "telegram_thin_client_enabled", True))
    )
    register_handlers(
        application,
        tools_bash_enabled=_resolve_tools_bash_enabled(runtime),
        private_message_handler=msg_handle_private_message,
        group_buffered_handler=msg_handle_group_buffered,
    )
    return application


async def bootstrap_telegram_application(
    application: Application,
    runtime: RuntimeContext,
    *,
    owner_user_id: int,
) -> None:
    me = await application.bot.get_me()
    runtime.bot_username = me.username or ""
    logger.info(
        "Team rollout config mode=%s dual_read=%s dual_write=%s",
        runtime.team_rollout_mode,
        runtime.team_dual_read_enabled,
        runtime.team_dual_write_enabled,
    )
    logger.info(
        "Runtime dispatch health mode=%s is_runner=%s",
        runtime.dispatch_mode,
        runtime.dispatch_is_runner,
    )
    if runtime.team_rollout_mode == "team" and not runtime.team_dual_read_enabled:
        logger.warning("Team rollout mode is 'team' with dual_read disabled; fallback diagnostics are limited")
    if _resolve_tools_bash_enabled(runtime) and not _resolve_tools_bash_password(runtime):
        logger.warning("BASH_DANGEROUS_PASSWORD is empty; privileged bash commands will be blocked")

    storage = _resolve_storage(runtime)
    reconcile_plan = await build_reconcile_active_groups_plan(application.bot, storage)
    with storage.transaction(immediate=True):
        apply_reconcile_active_groups_writes(storage, reconcile_plan.writes)
    logger.info(
        "startup group reconcile checked=%s deactivated=%s",
        reconcile_plan.checked,
        reconcile_plan.deactivated,
    )
    owner_commands = [
        BotCommand("groups", "Список групп и выбор"),
        BotCommand("roles", "Список master-ролей"),
        BotCommand("tools", "Список инструментов"),
    ]
    if _resolve_tools_bash_enabled(runtime):
        owner_commands.append(BotCommand("bash", "Выполнить bash команду"))
    await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_user_id))
    await application.bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
    await application.bot.set_my_commands([], scope=BotCommandScopeAllGroupChats())
    await application.bot.set_my_commands([], scope=BotCommandScopeDefault())


def resolve_bootstrap_owner_user_id(runtime: RuntimeContext, configured_owner_user_id: int) -> int:
    authz_service = getattr(runtime, "authz_service", None)
    if authz_service is None:
        return int(configured_owner_user_id)
    actor = AuthzActor(user_id=int(configured_owner_user_id))
    result = authz_service.authorize(action=action_for_bootstrap_admin(), actor=actor, resource_ctx=None)
    if result.is_error:
        raise InterfaceConfigError("Configured owner_user_id is not authorized for telegram bootstrap")
    if not (result.value and result.value.allowed):
        raise InterfaceConfigError("Configured owner_user_id is denied by authz policy for telegram bootstrap")
    return int(configured_owner_user_id)


class TelegramInterfaceAdapter:
    interface_id = "telegram"

    def __init__(
        self,
        *,
        core_port: CorePort,
        runtime: RuntimeContext,
        config: dict[str, Any],
    ) -> None:
        self._core_port = core_port
        self._runtime = runtime
        self._config = config
        self._application: Application | None = None
        self._initialized = False

    async def start(self) -> None:
        if self._application is None:
            token = str(self._config.get("telegram_bot_token", "")).strip()
            if not token:
                raise InterfaceConfigError("telegram_bot_token is required for telegram interface adapter")
            self._application = build_telegram_application(token, self._runtime)
        if self._initialized:
            return
        configured_owner_user_id = int(self._config.get("owner_user_id", self._runtime.owner_user_id))
        owner_user_id = resolve_bootstrap_owner_user_id(self._runtime, configured_owner_user_id)
        await self._application.initialize()
        await bootstrap_telegram_application(self._application, self._runtime, owner_user_id=owner_user_id)
        await self._application.start()
        await self._application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Release bot started as @%s", self._runtime.bot_username)
        self._initialized = True

    async def stop(self) -> None:
        if self._application is None or not self._initialized:
            return
        await self._application.stop()
        await self._application.shutdown()
        self._initialized = False


def create_adapter(*, core_port: CorePort, runtime: RuntimeContext, config: dict[str, Any]) -> TelegramInterfaceAdapter:
    return TelegramInterfaceAdapter(core_port=core_port, runtime=runtime, config=config)
