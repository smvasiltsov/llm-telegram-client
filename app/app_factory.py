from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

import httpx
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.auth import AuthService
from app.config import AppConfig
from app.handlers.callbacks import handle_callback as cb_handle_callback
from app.handlers.commands import (
    handle_bash as cmd_handle_bash,
)
from app.handlers.commands import (
    handle_group_roles as cmd_handle_group_roles,
    handle_groups as cmd_handle_groups,
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
from app.llm_executor import LLMExecutor
from app.llm_providers import load_provider_registry
from app.llm_router import LLMRouter
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.plugin_server import PluginServerConfig, PluginTextServer
from app.plugins import load_plugins
from app.roles_registry import seed_roles
from app.runtime import RuntimeContext
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.storage import Storage
from app.tools import BashTool, ToolMCPAdapter, ToolRegistry, ToolService


HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def register_handlers(
    application: Application,
    *,
    tools_bash_enabled: bool,
    private_message_handler: HandlerFn,
    group_buffered_handler: HandlerFn,
) -> None:
    application.add_handler(CommandHandler("groups", cmd_handle_groups, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("tools", cmd_handle_tools, filters=filters.ChatType.PRIVATE))
    if tools_bash_enabled:
        application.add_handler(CommandHandler("bash", cmd_handle_bash, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("roles", cmd_handle_group_roles, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_set_prompt", cmd_handle_role_set_prompt, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("role_reset_session", cmd_handle_role_reset_session, filters=filters.ChatType.PRIVATE))
    application.add_handler(CallbackQueryHandler(cb_handle_callback))
    application.add_handler(ChatMemberHandler(member_handle_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, member_handle_group_seen), group=0)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, private_message_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), group_buffered_handler), group=1)


def build_application(
    config: AppConfig,
    runtime: RuntimeContext,
) -> Application:
    application = ApplicationBuilder().token(config.telegram_bot_token).build()
    application.bot_data.update(runtime.to_bot_data())
    register_handlers(
        application,
        tools_bash_enabled=runtime.tools_bash_enabled,
        private_message_handler=msg_handle_private_message,
        group_buffered_handler=msg_handle_group_buffered,
    )
    return application


def build_services(
    config: AppConfig,
    env_values: Mapping[str, str],
    *,
    bot_username: str = "",
    providers_dir: Path = Path("llm_providers"),
    plugins_dir: Path = Path("plugins"),
    base_cwd: Path | None = None,
) -> RuntimeContext:
    tools_bash_password = str(env_values.get("BASH_DANGEROUS_PASSWORD", "")).strip()
    return build_runtime(
        config=config,
        bot_username=bot_username,
        tools_bash_password=tools_bash_password,
        providers_dir=providers_dir,
        plugins_dir=plugins_dir,
        base_cwd=base_cwd or Path.cwd(),
    )


def build_runtime(
    *,
    config: AppConfig,
    bot_username: str,
    tools_bash_password: str,
    providers_dir: Path,
    plugins_dir: Path,
    base_cwd: Path,
) -> RuntimeContext:
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
        default_cwd = Path(config.tools_bash_default_cwd).expanduser()
        if not default_cwd.is_absolute():
            default_cwd = (base_cwd / default_cwd).resolve()
        else:
            default_cwd = default_cwd.resolve()
        allowed_workdirs = []
        for item in config.tools_bash_allowed_workdirs:
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = (base_cwd / path).resolve()
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
    plugin_manager = load_plugins(plugins_dir)
    plugin_server = PluginTextServer(
        storage,
        PluginServerConfig(
            host=config.plugin_server_host,
            port=config.plugin_server_port,
            enabled=config.plugin_server_enabled,
        ),
    )

    storage.reset_authorizations()
    return RuntimeContext(
        bot_username=bot_username,
        storage=storage,
        cipher=cipher,
        llm_router=llm_router,
        llm_executor=llm_executor,
        session_resolver=session_resolver,
        pending_store=pending_store,
        message_buffer=message_buffer,
        private_buffer=private_buffer,
        auth_service=auth_service,
        owner_user_id=config.owner_user_id,
        require_bot_mention=config.require_bot_mention,
        pending_prompts={},
        pending_role_ops={},
        pending_user_fields=pending_user_fields,
        provider_registry=provider_registry,
        provider_models=provider_models,
        provider_model_map={m.full_id: m for m in provider_models},
        default_provider_id=default_provider_id,
        allow_raw_html=config.allow_raw_html,
        formatting_mode=config.formatting_mode,
        plugin_manager=plugin_manager,
        plugin_server=plugin_server,
        tool_service=tool_service,
        tools_bash_enabled=tools_bash_enabled,
        tools_bash_password=tools_bash_password,
        tools_bash_safe_commands=list(config.tools_bash_safe_commands),
        pending_bash_auth={},
        bash_cwd_by_user={},
        tool_mcp_adapter=tool_mcp_adapter,
        llm_clients=llm_clients,
    )
