from .dependencies import (
    attach_runtime_dependencies_to_app_state,
    provide_authz_dependencies,
    provide_pending_replay_dependencies,
    provide_queue_status_dependencies,
    provide_runtime_dispatch_health,
    provide_runtime_dependency_provider,
    provide_runtime_orchestration_dependencies,
    provide_storage_uow_dependencies,
    provide_tooling_dependencies,
)
from .error_mapping import ApiMappedError, map_exception_to_api_error, map_result_error_to_api


def build_read_only_fastapi_app(runtime) -> object:
    from .read_only_app import build_read_only_fastapi_app as _builder

    return _builder(runtime)

__all__ = [
    "ApiMappedError",
    "attach_runtime_dependencies_to_app_state",
    "build_read_only_fastapi_app",
    "map_exception_to_api_error",
    "map_result_error_to_api",
    "provide_authz_dependencies",
    "provide_pending_replay_dependencies",
    "provide_queue_status_dependencies",
    "provide_runtime_dispatch_health",
    "provide_runtime_dependency_provider",
    "provide_runtime_orchestration_dependencies",
    "provide_storage_uow_dependencies",
    "provide_tooling_dependencies",
]
