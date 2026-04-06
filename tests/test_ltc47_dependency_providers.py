from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.application.dependencies import RuntimeContextDependencyProvider, resolve_storage_uow_dependencies
from app.interfaces.api.dependencies import (
    attach_runtime_dependencies_to_app_state,
    provide_runtime_dispatch_health,
    provide_runtime_dependency_provider,
    provide_storage_uow_dependencies,
)


def _runtime_stub() -> SimpleNamespace:
    return SimpleNamespace(
        authz_service=object(),
        storage=object(),
        llm_router=object(),
        llm_executor=object(),
        session_resolver=object(),
        provider_registry={},
        provider_models=[],
        provider_model_map={},
        default_provider_id="default",
        cipher=object(),
        role_runtime_status_service=object(),
        role_dispatch_queue_service=object(),
        free_transition_delay_sec=1,
        pending_store=object(),
        pending_user_fields=object(),
        pending_prompts={},
        pending_role_ops={},
        tool_service=object(),
        pending_bash_auth={},
        bash_cwd_by_user={},
        tools_bash_password="p",
        tools_bash_enabled=False,
        dispatch_mode="single-runner",
        dispatch_is_runner=False,
        queue_backend="in-memory",
        started_at="2026-04-05T00:00:00+00:00",
    )


class LTC47DependencyProviderTests(unittest.TestCase):
    def test_runtime_to_bot_data_exposes_runtime_dependencies(self) -> None:
        runtime = _runtime_stub()
        provider = RuntimeContextDependencyProvider(runtime=runtime)
        bot_data = {"runtime": runtime, "runtime_dependencies": provider}
        result = resolve_storage_uow_dependencies(bot_data)
        self.assertTrue(result.is_ok)
        self.assertIs(result.value.storage, runtime.storage)

    def test_api_provider_from_app_state_runtime(self) -> None:
        runtime = _runtime_stub()
        state = SimpleNamespace(runtime=runtime)
        provider_result = provide_runtime_dependency_provider(state)
        self.assertTrue(provider_result.is_ok)
        self.assertIsNotNone(provider_result.value)
        storage_result = provide_storage_uow_dependencies(state)
        self.assertTrue(storage_result.is_ok)
        self.assertIs(storage_result.value.storage, runtime.storage)

    def test_api_attach_runtime_dependencies_to_app_state(self) -> None:
        runtime = _runtime_stub()
        state = SimpleNamespace()
        attach_runtime_dependencies_to_app_state(state, runtime)
        self.assertTrue(hasattr(state, "runtime_dependencies"))
        provider_result = provide_runtime_dependency_provider(state)
        self.assertTrue(provider_result.is_ok)
        self.assertIsNotNone(provider_result.value)

    def test_api_runtime_dispatch_health_provider(self) -> None:
        runtime = _runtime_stub()
        state = SimpleNamespace(runtime=runtime)
        health_result = provide_runtime_dispatch_health(state)
        self.assertTrue(health_result.is_ok)
        self.assertEqual(
            health_result.value,
            {
                "mode": "single-runner",
                "is_runner": False,
                "queue_backend": "in-memory",
                "started_at": "2026-04-05T00:00:00+00:00",
            },
        )


if __name__ == "__main__":
    unittest.main()
