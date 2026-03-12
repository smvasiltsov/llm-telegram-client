from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from app.security import TokenCipher
from app.session_resolver import SessionResolver
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage
from app.tools import ToolMCPAdapter, ToolService


@dataclass
class RuntimeContext:
    bot_username: str
    storage: Storage
    cipher: TokenCipher
    llm_router: LLMRouter
    llm_executor: LLMExecutor
    session_resolver: SessionResolver
    pending_store: PendingStore
    message_buffer: MessageBuffer
    private_buffer: MessageBuffer
    auth_service: AuthService
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

    def to_bot_data(self) -> dict[str, Any]:
        return {"runtime": self}
