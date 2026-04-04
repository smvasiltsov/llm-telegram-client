from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.application.contracts import ErrorCode, Result

from .contracts import (
    AuthzDependencies,
    PendingReplayDependencies,
    QueueStatusDependencies,
    RuntimeOrchestrationDependencies,
    StorageUowDependencies,
    ToolingDependencies,
)

if TYPE_CHECKING:
    from app.runtime import RuntimeContext


@dataclass(frozen=True)
class RuntimeContextDependencyProvider:
    runtime: "RuntimeContext"

    def _missing_dependency(self, name: str) -> Result[Any]:
        return Result.fail(
            ErrorCode.INTERNAL_UNEXPECTED,
            "Runtime dependency is not configured",
            details={"entity": "runtime_dependency", "id": name, "cause": "missing"},
        )

    def _require_attr(self, name: str) -> tuple[bool, Any]:
        value = getattr(self.runtime, name, None)
        if value is None:
            return False, None
        return True, value

    def authz(self) -> Result[AuthzDependencies]:
        ok, authz_service = self._require_attr("authz_service")
        if not ok:
            return self._missing_dependency("authz_service")
        return Result.ok(AuthzDependencies(authz_service=authz_service))

    def runtime_orchestration(self) -> Result[RuntimeOrchestrationDependencies]:
        required = [
            "storage",
            "llm_router",
            "llm_executor",
            "session_resolver",
            "provider_registry",
            "provider_models",
            "provider_model_map",
            "default_provider_id",
            "cipher",
        ]
        for name in required:
            ok, _ = self._require_attr(name)
            if not ok:
                return self._missing_dependency(name)
        return Result.ok(
            RuntimeOrchestrationDependencies(
                storage=self.runtime.storage,
                llm_router=self.runtime.llm_router,
                llm_executor=self.runtime.llm_executor,
                session_resolver=self.runtime.session_resolver,
                provider_registry=self.runtime.provider_registry,
                provider_models=self.runtime.provider_models,
                provider_model_map=self.runtime.provider_model_map,
                default_provider_id=self.runtime.default_provider_id,
                cipher=self.runtime.cipher,
            )
        )

    def queue_status(self) -> Result[QueueStatusDependencies]:
        required = [
            "role_runtime_status_service",
            "role_dispatch_queue_service",
            "free_transition_delay_sec",
        ]
        for name in required:
            ok, _ = self._require_attr(name)
            if not ok:
                return self._missing_dependency(name)
        return Result.ok(
            QueueStatusDependencies(
                runtime_status_service=self.runtime.role_runtime_status_service,
                dispatch_queue_service=self.runtime.role_dispatch_queue_service,
                free_transition_delay_sec=int(self.runtime.free_transition_delay_sec),
            )
        )

    def storage_uow(self) -> Result[StorageUowDependencies]:
        ok, storage = self._require_attr("storage")
        if not ok:
            return self._missing_dependency("storage")
        return Result.ok(StorageUowDependencies(storage=storage))

    def pending_replay(self) -> Result[PendingReplayDependencies]:
        required = [
            "pending_store",
            "pending_user_fields",
            "pending_prompts",
            "pending_role_ops",
        ]
        for name in required:
            ok, _ = self._require_attr(name)
            if not ok:
                return self._missing_dependency(name)
        return Result.ok(
            PendingReplayDependencies(
                pending_store=self.runtime.pending_store,
                pending_user_fields=self.runtime.pending_user_fields,
                pending_prompts=self.runtime.pending_prompts,
                pending_role_ops=self.runtime.pending_role_ops,
            )
        )

    def tooling(self) -> Result[ToolingDependencies]:
        required = [
            "tool_service",
            "pending_bash_auth",
            "bash_cwd_by_user",
            "tools_bash_password",
            "tools_bash_enabled",
        ]
        for name in required:
            ok, _ = self._require_attr(name)
            if not ok:
                return self._missing_dependency(name)
        return Result.ok(
            ToolingDependencies(
                tool_service=self.runtime.tool_service,
                pending_bash_auth=self.runtime.pending_bash_auth,
                bash_cwd_by_user=self.runtime.bash_cwd_by_user,
                tools_bash_password=self.runtime.tools_bash_password,
                tools_bash_enabled=bool(self.runtime.tools_bash_enabled),
            )
        )


def build_runtime_dependency_provider(runtime: "RuntimeContext") -> RuntimeContextDependencyProvider:
    return RuntimeContextDependencyProvider(runtime=runtime)
