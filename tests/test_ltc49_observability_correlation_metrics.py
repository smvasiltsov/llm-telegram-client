from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

telegram_module = sys.modules.get("telegram")
if telegram_module is None:
    telegram_module = types.ModuleType("telegram")
    sys.modules["telegram"] = telegram_module
telegram_ext = sys.modules.get("telegram.ext")
if telegram_ext is None:
    telegram_ext = types.ModuleType("telegram.ext")
    sys.modules["telegram.ext"] = telegram_ext
telegram_constants = sys.modules.get("telegram.constants")
if telegram_constants is None:
    telegram_constants = types.ModuleType("telegram.constants")
    sys.modules["telegram.constants"] = telegram_constants
telegram_error = sys.modules.get("telegram.error")
if telegram_error is None:
    telegram_error = types.ModuleType("telegram.error")
    sys.modules["telegram.error"] = telegram_error


class _Dummy:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _ContextTypes:
    DEFAULT_TYPE = object


class _ParseMode:
    HTML = "HTML"


class _BadRequest(Exception):
    pass


if not hasattr(telegram_module, "Update"):
    telegram_module.Update = _Dummy
if not hasattr(telegram_module, "InlineKeyboardButton"):
    telegram_module.InlineKeyboardButton = _Dummy
if not hasattr(telegram_module, "InlineKeyboardMarkup"):
    telegram_module.InlineKeyboardMarkup = _Dummy
if not hasattr(telegram_module, "WebAppInfo"):
    telegram_module.WebAppInfo = _Dummy
if not hasattr(telegram_ext, "ContextTypes"):
    telegram_ext.ContextTypes = _ContextTypes
if not hasattr(telegram_constants, "ParseMode"):
    telegram_constants.ParseMode = _ParseMode
if not hasattr(telegram_error, "BadRequest"):
    telegram_error.BadRequest = _BadRequest
telegram_module.ext = telegram_ext
telegram_module.constants = telegram_constants
telegram_module.error = telegram_error

from app.application.contracts import NoopMetricsPort, RuntimeOperation, sanitize_metric_labels
from app.application.observability import clear_correlation_id, get_correlation_id
from app.application.use_cases.runtime_orchestration import execute_run_chain_operation
from app.models import Role, TeamRole
from app.services.role_pipeline import execute_role_request


class _FakeMetricsPort(NoopMetricsPort):
    def __init__(self) -> None:
        self.increments: list[tuple[str, int, dict[str, str]]] = []
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, name: str, *, labels=None, value: int = 1) -> None:  # type: ignore[override]
        self.increments.append((name, int(value), dict(labels or {})))

    def observe_ms(self, name: str, *, value_ms: float, labels=None) -> None:  # type: ignore[override]
        self.observations.append((name, float(value_ms), dict(labels or {})))


class _FakeStorage:
    def __init__(self, team_role: TeamRole) -> None:
        self._team_role = team_role

    def get_team_role(self, team_id: int, role_id: int) -> TeamRole:
        assert team_id == self._team_role.team_id
        assert role_id == self._team_role.role_id
        return self._team_role

    def list_role_skills_for_team_role(self, team_role_id: int, enabled_only: bool = True):  # noqa: ANN001
        _ = enabled_only
        assert team_role_id == self._team_role.team_role_id
        return []

    def resolve_team_role_id(self, team_id: int, role_id: int, ensure_exists: bool = False):  # noqa: ANN001
        _ = ensure_exists
        assert team_id == self._team_role.team_id
        assert role_id == self._team_role.role_id
        return self._team_role.team_role_id

    def list_role_prepost_processing_for_team_role(self, team_role_id: int, enabled_only: bool = True):  # noqa: ANN001
        _ = enabled_only
        assert team_role_id == self._team_role.team_role_id
        return []


class _FakeResolver:
    async def resolve(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return "session-1"


class _FakeExecutor:
    async def send_with_retries(self, *args, **kwargs) -> str:  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return "ok"


class _FakeStatusService:
    def __init__(self) -> None:
        self._calls = 0

    def cleanup_stale(self) -> int:
        return 0

    def acquire_busy(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        self._calls += 1
        if self._calls == 1:
            return SimpleNamespace(acquired=False, status=None, blockers=[])
        return SimpleNamespace(acquired=True, status=None, blockers=[])

    def release_busy(self, **kwargs) -> None:  # noqa: ANN003
        _ = kwargs

    def update_preview(self, **kwargs) -> None:  # noqa: ANN003
        _ = kwargs


class LTC49ObservabilityCorrelationMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_run_chain_reuses_external_correlation_id(self) -> None:
        clear_correlation_id()
        metrics = _FakeMetricsPort()
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"metrics_port": metrics}))
        captured: list[str | None] = []

        async def run_chain_stub(**_: object) -> SimpleNamespace:
            captured.append(get_correlation_id())
            return SimpleNamespace(completed_roles=1, had_error=False, stopped=False)

        result = await execute_run_chain_operation(
            context=context,
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="token",
            roles=[],
            user_text="secret text",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=True,
            save_pending_on_unauthorized=False,
            correlation_id="external-corr-id",
            run_chain_fn=run_chain_stub,
        )

        self.assertTrue(result.is_ok)
        self.assertEqual(captured, ["external-corr-id"])
        started = [item for item in metrics.increments if item[0] == "runtime_operation_total" and item[2].get("result") == "started"]
        success = [item for item in metrics.increments if item[0] == "runtime_operation_total" and item[2].get("result") == "success"]
        self.assertTrue(started)
        self.assertTrue(success)
        self.assertTrue(any(item[0] == "runtime_operation_latency_ms" for item in metrics.observations))

    async def test_execute_run_chain_generates_correlation_id_when_missing(self) -> None:
        clear_correlation_id()
        metrics = _FakeMetricsPort()
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"metrics_port": metrics}))
        captured: list[str | None] = []

        async def run_chain_stub(**_: object) -> SimpleNamespace:
            captured.append(get_correlation_id())
            return SimpleNamespace(completed_roles=1, had_error=False, stopped=False)

        result = await execute_run_chain_operation(
            context=context,
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="token",
            roles=[],
            user_text="hi",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=True,
            save_pending_on_unauthorized=False,
            run_chain_fn=run_chain_stub,
        )

        self.assertTrue(result.is_ok)
        self.assertEqual(len(captured), 1)
        self.assertIsNotNone(captured[0])
        self.assertEqual(len(str(captured[0])), 32)

    async def test_pending_replay_failure_emits_error_metrics(self) -> None:
        clear_correlation_id()
        metrics = _FakeMetricsPort()
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"metrics_port": metrics}))

        async def run_chain_stub(**_: object) -> SimpleNamespace:
            raise RuntimeError("boom")

        result = await execute_run_chain_operation(
            context=context,
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="token",
            roles=[],
            user_text="hi",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=False,
            save_pending_on_unauthorized=False,
            chain_origin="pending",
            operation=RuntimeOperation.PENDING_REPLAY,
            run_chain_fn=run_chain_stub,
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.error.code, "runtime.replay_failed")
        failed_runtime = [
            item
            for item in metrics.increments
            if item[0] == "runtime_operation_total"
            and item[2].get("result") == "failed"
            and item[2].get("error_code") == "runtime.replay_failed"
        ]
        failed_pending = [
            item
            for item in metrics.increments
            if item[0] == "runtime_pending_replay_total"
            and item[2].get("result") == "failed"
            and item[2].get("error_code") == "runtime.replay_failed"
        ]
        self.assertTrue(failed_runtime)
        self.assertTrue(failed_pending)

    async def test_execute_role_request_emits_busy_conflict_metric(self) -> None:
        clear_correlation_id()
        metrics = _FakeMetricsPort()
        role = Role(
            role_id=5,
            role_name="dev",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        team_role = TeamRole(
            team_id=11,
            role_id=5,
            team_role_id=77,
            system_prompt_override=None,
            extra_instruction_override=None,
            display_name=None,
            model_override=None,
            user_prompt_suffix=None,
            user_reply_prefix=None,
            enabled=True,
            mode="normal",
            is_active=True,
        )
        runtime = SimpleNamespace(
            storage=_FakeStorage(team_role),
            provider_registry={},
            provider_models=[],
            provider_model_map={},
            llm_executor=_FakeExecutor(),
            session_resolver=_FakeResolver(),
            prepost_processing_registry=SimpleNamespace(get=lambda *_: None),
            metrics_port=metrics,
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))
        fake_status = _FakeStatusService()

        with (
            patch("app.services.role_pipeline._runtime_status_service", return_value=fake_status),
            patch("app.services.role_pipeline.asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            result = await execute_role_request(
                context=context,
                team_id=11,
                user_id=100,
                role=role,
                session_token="token",
                user_text="hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["dev"],
                recipient="dev",
                wait_until_available=True,
                queue_request_id="q-1",
                correlation_id="corr-1",
                operation=RuntimeOperation.RUN_CHAIN.value,
            )
        self.assertEqual(result.response_text, "ok")
        busy_conflicts = [
            item
            for item in metrics.increments
            if item[0] == "runtime_busy_conflict_total"
            and item[2].get("error_code") == "runtime.busy_conflict"
        ]
        self.assertTrue(busy_conflicts)

    def test_metric_labels_drop_pii_fields(self) -> None:
        labels = sanitize_metric_labels(
            {
                "operation": "runtime.run_chain",
                "result": "success",
                "error_code": "",
                "transport": "telegram",
                "user_id": "12345",
                "text": "hello secret",
            }
        )
        self.assertEqual(set(labels.keys()), {"operation", "result", "error_code", "transport"})
        self.assertNotIn("user_id", labels)
        self.assertNotIn("text", labels)


if __name__ == "__main__":
    unittest.main()
