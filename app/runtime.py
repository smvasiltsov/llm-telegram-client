from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from app.auth import AuthService
from app.llm_executor import LLMExecutor
from app.llm_router import LLMRouter
from app.message_buffer import MessageBuffer
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.plugin_server import PluginTextServer
from app.plugins import PluginManager
from app.prepost_processing.registry import PrePostProcessingRegistry
from app.role_catalog import RoleCatalog
from app.security import TokenCipher
from app.services.role_dispatch_queue import RoleDispatchQueueService
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.session_resolver import SessionResolver
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage
from app.tools import ToolMCPAdapter, ToolService

if TYPE_CHECKING:
    from app.application.authz import AuthzService
    from app.application.dependencies import RuntimeDependencyProvider


@dataclass
class RuntimeContext:
    bot_username: str
    storage: Storage
    cipher: TokenCipher
    llm_router: LLMRouter
    llm_executor: LLMExecutor
    session_resolver: SessionResolver
    role_runtime_status_service: RoleRuntimeStatusService
    role_dispatch_queue_service: RoleDispatchQueueService
    pending_store: PendingStore
    message_buffer: MessageBuffer
    private_buffer: MessageBuffer
    auth_service: AuthService
    metrics_port: Any
    authz_service: "AuthzService"
    owner_user_id: int
    require_bot_mention: bool
    orchestrator_max_chain_auto_steps: int
    pending_prompts: dict[int, tuple[int, int]]
    pending_role_ops: dict[int, dict[str, Any]]
    pending_user_fields: PendingUserFieldStore
    provider_registry: dict[str, Any]
    provider_models: list[Any]
    provider_model_map: dict[str, Any]
    default_provider_id: str
    allow_raw_html: bool
    formatting_mode: str
    skills_usage_prompt: str
    skills_max_steps_per_request: int
    skills_followup_mode: str
    prepost_processing_registry: PrePostProcessingRegistry
    skills_registry: SkillRegistry
    skills_service: SkillService
    plugin_manager: PluginManager
    plugin_server: PluginTextServer
    tool_service: ToolService
    tools_bash_enabled: bool
    tools_bash_password: str
    tools_bash_safe_commands: list[str]
    pending_bash_auth: dict[int, dict[str, Any]]
    bash_cwd_by_user: dict[int, str]
    tool_mcp_adapter: ToolMCPAdapter
    llm_clients: dict[str, httpx.AsyncClient]
    team_dual_read_enabled: bool
    team_dual_write_enabled: bool
    team_rollout_mode: str
    interface_active: str
    interface_modules_dir: str
    interface_runtime_mode: str
    free_transition_delay_sec: int
    skills_to_llm_delay_sec: int
    role_catalog: RoleCatalog
    dispatch_mode: str = "single-instance"
    dispatch_is_runner: bool = True
    queue_backend: str = "in-memory"
    started_at: str | None = None
    dependency_provider: "RuntimeDependencyProvider | None" = None

    def to_bot_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "runtime": self,
            "runtime_dispatch_health": {
                "mode": self.dispatch_mode,
                "is_runner": bool(self.dispatch_is_runner),
            },
        }
        if self.dependency_provider is not None:
            data["runtime_dependencies"] = self.dependency_provider
        return data
