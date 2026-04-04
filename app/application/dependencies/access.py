from __future__ import annotations

from typing import Any, Mapping

from app.application.contracts import ErrorCode, Result

from .contracts import (
    AuthzDependencies,
    PendingReplayDependencies,
    QueueStatusDependencies,
    RuntimeOrchestrationDependencies,
    StorageUowDependencies,
    ToolingDependencies,
)
from .providers import RuntimeContextDependencyProvider, build_runtime_dependency_provider


def _dependency_not_ready(message: str, *, details: Mapping[str, Any] | None = None) -> Result[Any]:
    return Result.fail(
        ErrorCode.INTERNAL_UNEXPECTED,
        message,
        details=details,
    )


def resolve_provider_from_bot_data(bot_data: Mapping[str, Any]) -> Result[RuntimeContextDependencyProvider]:
    runtime = bot_data.get("runtime")
    if runtime is None:
        return _dependency_not_ready(
            "Runtime context is not attached to bot_data",
            details={"entity": "runtime_context", "cause": "missing"},
        )
    return Result.ok(build_runtime_dependency_provider(runtime))


def resolve_authz_dependencies(bot_data: Mapping[str, Any]) -> Result[AuthzDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Authz dependencies are unavailable",
            details={"entity": "authz_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.authz()


def resolve_runtime_orchestration_dependencies(
    bot_data: Mapping[str, Any],
) -> Result[RuntimeOrchestrationDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Runtime orchestration dependencies are unavailable",
            details={"entity": "runtime_orchestration_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.runtime_orchestration()


def resolve_queue_status_dependencies(bot_data: Mapping[str, Any]) -> Result[QueueStatusDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Queue/status dependencies are unavailable",
            details={"entity": "queue_status_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.queue_status()


def resolve_storage_uow_dependencies(bot_data: Mapping[str, Any]) -> Result[StorageUowDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Storage UoW dependencies are unavailable",
            details={"entity": "storage_uow_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.storage_uow()


def resolve_pending_replay_dependencies(bot_data: Mapping[str, Any]) -> Result[PendingReplayDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Pending/replay dependencies are unavailable",
            details={"entity": "pending_replay_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.pending_replay()


def resolve_tooling_dependencies(bot_data: Mapping[str, Any]) -> Result[ToolingDependencies]:
    provider_result = resolve_provider_from_bot_data(bot_data)
    if provider_result.is_error or provider_result.value is None:
        return _dependency_not_ready(
            "Tooling dependencies are unavailable",
            details={"entity": "tooling_dependencies", "cause": "provider_unavailable"},
        )
    return provider_result.value.tooling()

