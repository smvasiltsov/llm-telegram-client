from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.application.contracts import Result

if TYPE_CHECKING:
    from app.application.authz import AuthzService
    from app.llm_executor import LLMExecutor
    from app.llm_router import LLMRouter
    from app.pending_store import PendingStore
    from app.pending_user_fields import PendingUserFieldStore
    from app.security import TokenCipher
    from app.services.role_dispatch_queue import RoleDispatchQueueService
    from app.services.role_runtime_status import RoleRuntimeStatusService
    from app.session_resolver import SessionResolver
    from app.storage import Storage
    from app.tools import ToolService


@dataclass(frozen=True)
class AuthzDependencies:
    authz_service: "AuthzService"


@dataclass(frozen=True)
class RuntimeOrchestrationDependencies:
    storage: "Storage"
    llm_router: "LLMRouter"
    llm_executor: "LLMExecutor"
    session_resolver: "SessionResolver"
    provider_registry: dict[str, Any]
    provider_models: list[Any]
    provider_model_map: dict[str, Any]
    default_provider_id: str
    cipher: "TokenCipher"


@dataclass(frozen=True)
class QueueStatusDependencies:
    runtime_status_service: "RoleRuntimeStatusService"
    dispatch_queue_service: "RoleDispatchQueueService"
    free_transition_delay_sec: int


@dataclass(frozen=True)
class StorageUowDependencies:
    storage: "Storage"


@dataclass(frozen=True)
class PendingReplayDependencies:
    pending_store: "PendingStore"
    pending_user_fields: "PendingUserFieldStore"
    pending_prompts: dict[int, tuple[int, int]]
    pending_role_ops: dict[int, dict[str, Any]]


@dataclass(frozen=True)
class ToolingDependencies:
    tool_service: "ToolService"
    pending_bash_auth: dict[int, dict[str, Any]]
    bash_cwd_by_user: dict[int, str]
    tools_bash_password: str
    tools_bash_enabled: bool


class RuntimeDependencyProvider(Protocol):
    def authz(self) -> Result[AuthzDependencies]: ...

    def runtime_orchestration(self) -> Result[RuntimeOrchestrationDependencies]: ...

    def queue_status(self) -> Result[QueueStatusDependencies]: ...

    def storage_uow(self) -> Result[StorageUowDependencies]: ...

    def pending_replay(self) -> Result[PendingReplayDependencies]: ...

    def tooling(self) -> Result[ToolingDependencies]: ...

