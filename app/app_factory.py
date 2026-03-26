from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import httpx

from app.auth import AuthService
from app.config import AppConfig
from app.interfaces.telegram.adapter import build_telegram_application
from app.llm_executor import LLMExecutor
from app.llm_providers import load_provider_registry
from app.llm_router import LLMRouter
from app.message_buffer import MessageBuffer
from app.prepost_processing.registry import PrePostProcessingRegistry
from app.role_catalog import RoleCatalog
from app.role_catalog_export import export_roles_from_db_first_run
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.plugin_server import PluginServerConfig, PluginTextServer
from app.plugins import load_plugins
from app.roles_registry import seed_roles
from app.runtime import RuntimeContext
from app.security import TokenCipher
from app.services.role_dispatch_queue import RoleDispatchQueueService
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.session_resolver import SessionResolver
from app.skills import SkillRegistry, SkillService
from app.storage import Storage
from app.tools import BashTool, ToolMCPAdapter, ToolRegistry, ToolService

logger = logging.getLogger("bot")


def build_application(
    config: AppConfig,
    runtime: RuntimeContext,
) -> Any:
    return build_telegram_application(config.telegram_bot_token, runtime)


def build_services(
    config: AppConfig,
    env_values: Mapping[str, str],
    *,
    bot_username: str = "",
    providers_dir: Path = Path("llm_providers"),
    plugins_dir: Path = Path("plugins"),
    prepost_processing_dir: Path = Path("prepost_processing"),
    skills_dir: Path = Path("skills"),
    base_cwd: Path | None = None,
) -> RuntimeContext:
    tools_bash_password = str(env_values.get("BASH_DANGEROUS_PASSWORD", "")).strip()
    return build_runtime(
        config=config,
        bot_username=bot_username,
        tools_bash_password=tools_bash_password,
        providers_dir=providers_dir,
        plugins_dir=plugins_dir,
        prepost_processing_dir=prepost_processing_dir,
        skills_dir=skills_dir,
        base_cwd=base_cwd or Path.cwd(),
    )


def build_runtime(
    *,
    config: AppConfig,
    bot_username: str,
    tools_bash_password: str,
    providers_dir: Path,
    plugins_dir: Path,
    prepost_processing_dir: Path,
    skills_dir: Path,
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
    export_result = export_roles_from_db_first_run(storage, (base_cwd / "roles_catalog").resolve())
    role_catalog = RoleCatalog.load((base_cwd / "roles_catalog").resolve())
    storage.attach_role_catalog(role_catalog)

    cipher = TokenCipher(config.encryption_key)
    default_provider_id = next(iter(llm_clients.keys()))
    llm_router = LLMRouter(provider_registry, llm_clients, storage, default_provider_id=default_provider_id)
    llm_executor = LLMExecutor(llm_router)
    session_resolver = SessionResolver(storage, llm_router)
    role_runtime_status_service = RoleRuntimeStatusService(
        storage,
        free_transition_delay_sec=config.free_transition_delay_sec,
    )
    startup_cleaned = role_runtime_status_service.cleanup_stale()
    logger.info("startup stale runtime-status cleanup cleaned=%s", startup_cleaned)
    role_dispatch_queue_service = RoleDispatchQueueService()

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
    prepost_processing_registry = PrePostProcessingRegistry()
    prepost_processing_registry.discover(prepost_processing_dir)
    skills_registry = SkillRegistry()
    skills_registry.discover(skills_dir)
    skills_service = SkillService(skills_registry)
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
    if role_catalog.issues:
        for issue in role_catalog.issues:
            logger.warning("role_catalog issue path=%s reason=%s", issue.path, issue.reason)
    if export_result.skipped_by_marker:
        logger.info("role_catalog export skipped by marker")
    return RuntimeContext(
        bot_username=bot_username,
        storage=storage,
        cipher=cipher,
        llm_router=llm_router,
        llm_executor=llm_executor,
        session_resolver=session_resolver,
        role_runtime_status_service=role_runtime_status_service,
        role_dispatch_queue_service=role_dispatch_queue_service,
        pending_store=pending_store,
        message_buffer=message_buffer,
        private_buffer=private_buffer,
        auth_service=auth_service,
        owner_user_id=config.owner_user_id,
        require_bot_mention=config.require_bot_mention,
        orchestrator_max_chain_auto_steps=config.orchestrator_max_chain_auto_steps,
        pending_prompts={},
        pending_role_ops={},
        pending_user_fields=pending_user_fields,
        provider_registry=provider_registry,
        provider_models=provider_models,
        provider_model_map={m.full_id: m for m in provider_models},
        default_provider_id=default_provider_id,
        allow_raw_html=config.allow_raw_html,
        formatting_mode=config.formatting_mode,
        skills_usage_prompt=config.skills_usage_prompt,
        skills_max_steps_per_request=config.skills_max_steps_per_request,
        skills_followup_mode=config.skills_followup_mode,
        prepost_processing_registry=prepost_processing_registry,
        skills_registry=skills_registry,
        skills_service=skills_service,
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
        team_dual_read_enabled=config.team_dual_read_enabled,
        team_dual_write_enabled=config.team_dual_write_enabled,
        team_rollout_mode=config.team_rollout_mode,
        interface_active=config.interface_active,
        interface_modules_dir=config.interface_modules_dir,
        interface_runtime_mode=config.interface_runtime_mode,
        free_transition_delay_sec=config.free_transition_delay_sec,
        role_catalog=role_catalog,
    )
