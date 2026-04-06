from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.application.contracts import ErrorCode, Result
from app.application.dependencies import (
    RuntimeContextDependencyProvider,
    build_runtime_dependency_provider,
)
from app.application.dependencies.contracts import (
    AuthzDependencies,
    PendingReplayDependencies,
    QueueStatusDependencies,
    RuntimeOrchestrationDependencies,
    StorageUowDependencies,
    ToolingDependencies,
)


def _dependency_not_ready(message: str, *, details: dict[str, Any] | None = None) -> Result[Any]:
    return Result.fail(
        ErrorCode.INTERNAL_UNEXPECTED,
        message,
        details=details,
    )


def attach_runtime_dependencies_to_app_state(app_state: Any, runtime: Any) -> None:
    if not hasattr(app_state, "runtime"):
        setattr(app_state, "runtime", runtime)
    provider = getattr(runtime, "dependency_provider", None)
    if provider is None:
        provider = build_runtime_dependency_provider(runtime)
    setattr(app_state, "runtime_dependencies", provider)


def provide_runtime_dependency_provider(app_state: Any) -> Result[RuntimeContextDependencyProvider]:
    provider = getattr(app_state, "runtime_dependencies", None)
    if isinstance(provider, RuntimeContextDependencyProvider):
        return Result.ok(provider)

    runtime = getattr(app_state, "runtime", None)
    if runtime is None:
        return _dependency_not_ready(
            "Runtime dependencies are unavailable for API transport",
            details={"entity": "api_dependency_provider", "cause": "runtime_missing"},
        )
    return Result.ok(build_runtime_dependency_provider(runtime))


def _with_provider(app_state: Any) -> Result[RuntimeContextDependencyProvider]:
    provider_result = provide_runtime_dependency_provider(app_state)
    if provider_result.is_error or provider_result.value is None:
        return provider_result
    return provider_result


def provide_authz_dependencies(app_state: Any) -> Result[AuthzDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Authz dependencies are unavailable")
    return provider.value.authz()


def provide_runtime_orchestration_dependencies(app_state: Any) -> Result[RuntimeOrchestrationDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Runtime orchestration dependencies are unavailable")
    return provider.value.runtime_orchestration()


def provide_queue_status_dependencies(app_state: Any) -> Result[QueueStatusDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Queue/status dependencies are unavailable")
    return provider.value.queue_status()


def provide_storage_uow_dependencies(app_state: Any) -> Result[StorageUowDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Storage UoW dependencies are unavailable")
    return provider.value.storage_uow()


def provide_pending_replay_dependencies(app_state: Any) -> Result[PendingReplayDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Pending/replay dependencies are unavailable")
    return provider.value.pending_replay()


def provide_tooling_dependencies(app_state: Any) -> Result[ToolingDependencies]:
    provider = _with_provider(app_state)
    if provider.is_error or provider.value is None:
        return _dependency_not_ready("Tooling dependencies are unavailable")
    return provider.value.tooling()


def provide_runtime_dispatch_health(app_state: Any) -> Result[dict[str, Any]]:
    runtime = getattr(app_state, "runtime", None)
    if runtime is None:
        return _dependency_not_ready(
            "Runtime dispatch health is unavailable",
            details={"entity": "runtime_dispatch_health", "cause": "runtime_missing"},
        )
    return Result.ok(
        {
            "mode": str(getattr(runtime, "dispatch_mode", "single-instance")),
            "is_runner": bool(getattr(runtime, "dispatch_is_runner", True)),
            "queue_backend": str(getattr(runtime, "queue_backend", "in-memory")),
            "started_at": getattr(runtime, "started_at", None),
        }
    )


def build_app_state() -> SimpleNamespace:
    return SimpleNamespace()
