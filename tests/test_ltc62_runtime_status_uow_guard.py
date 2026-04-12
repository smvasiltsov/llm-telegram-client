from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

if "telegram" not in sys.modules:
    telegram_module = types.ModuleType("telegram")
    telegram_constants = types.ModuleType("telegram.constants")
    telegram_error = types.ModuleType("telegram.error")
    telegram_ext = types.ModuleType("telegram.ext")

    class _ParseMode:
        HTML = "HTML"
        MARKDOWN = "MARKDOWN"

    class _BadRequest(Exception):
        pass

    class _Dummy:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _ContextTypes:
        DEFAULT_TYPE = object

    telegram_constants.ParseMode = _ParseMode
    telegram_error.BadRequest = _BadRequest
    telegram_ext.ContextTypes = _ContextTypes
    telegram_module.constants = telegram_constants
    telegram_module.error = telegram_error
    telegram_module.ext = telegram_ext
    telegram_module.InlineKeyboardButton = _Dummy
    telegram_module.InlineKeyboardMarkup = _Dummy
    telegram_module.Update = _Dummy
    telegram_module.WebAppInfo = _Dummy

    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.constants"] = telegram_constants
    sys.modules["telegram.error"] = telegram_error
    sys.modules["telegram.ext"] = telegram_ext

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")
    httpx_module.HTTPStatusError = Exception
    sys.modules["httpx"] = httpx_module

from app.pending_store import PendingStore
from app.prepost_processing.registry import PrePostProcessingRegistry
from app.role_catalog import RoleCatalog
from app.services.role_pipeline import run_chain
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage


class _FakeModel:
    full_id = "provider:model"


class _FakeSessionResolver:
    async def resolve(self, telegram_user_id: int, team_id: int, role, session_token: str, model_override: str | None = None) -> str:
        return "session-1"


class _FakeLLMExecutor:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        team_role_id: int | None = None,
        retries: int = 2,
    ) -> str:
        _ = team_role_id
        if not self._responses:
            raise AssertionError("No fake LLM responses left")
        return self._responses.pop(0)

    def provider_id_for_model(self, model_override: str | None) -> str:
        return "provider"


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, *, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append(text)


class _NoopPluginManager:
    def apply_postprocess(self, payload: dict, ctx_payload: dict) -> dict:
        return payload


class LTC62RuntimeStatusUowGuardTests(unittest.IsolatedAsyncioTestCase):
    def _seed_team_role(self, storage: Storage, *, team_public_id: str, role_name: str) -> tuple[int, int]:
        with storage.transaction(immediate=True):
            team = storage.upsert_team(public_id=team_public_id, name=team_public_id)
            role = storage.upsert_role(
                role_name=role_name,
                description=f"{role_name} desc",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role = storage.ensure_team_role(team.team_id, role.role_id)
        if team_role.team_role_id is None:
            raise AssertionError("team_role_id missing")
        return int(team_role.team_role_id), int(role.role_id)

    def test_cleanup_stale_runs_inside_transaction(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc62_cleanup.sqlite3")
            team_role_id, _ = self._seed_team_role(storage, team_public_id="t1", role_name="worker")
            with storage.transaction(immediate=True):
                storage.mark_team_role_runtime_busy(
                    team_role_id,
                    busy_request_id="req-stale",
                    busy_owner_user_id=1,
                    busy_origin="group",
                    preview_text="stale task",
                    preview_source="user",
                    busy_since="2026-03-26T10:00:00+00:00",
                    lease_expires_at="2026-03-26T10:00:30+00:00",
                    now="2026-03-26T10:00:00+00:00",
                )

            service = RoleRuntimeStatusService(storage, busy_lease_seconds=30, free_transition_delay_sec=20)
            storage.enable_write_uow_guard()
            observed_tx_depths: list[int] = []
            original = storage.cleanup_stale_busy_team_roles

            def _wrapped(*args, **kwargs):
                observed_tx_depths.append(storage._tx_depth)
                return original(*args, **kwargs)

            with patch.object(storage, "cleanup_stale_busy_team_roles", side_effect=_wrapped):
                changed = service.cleanup_stale()

            self.assertGreaterEqual(changed, 1)
            self.assertTrue(observed_tx_depths)
            self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    def test_release_busy_delay_path_runs_inside_transaction(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc62_release.sqlite3")
            team_role_id, _ = self._seed_team_role(storage, team_public_id="t1", role_name="worker")
            service = RoleRuntimeStatusService(storage, free_transition_delay_sec=10)
            service.acquire_busy(
                team_role_id=team_role_id,
                busy_request_id="req-1",
                busy_owner_user_id=5,
                busy_origin="group",
                preview_text="work",
                preview_source="user",
            )

            storage.enable_write_uow_guard()
            observed_tx_depths: list[int] = []
            original = storage.mark_team_role_runtime_release_requested

            def _wrapped(*args, **kwargs):
                observed_tx_depths.append(storage._tx_depth)
                return original(*args, **kwargs)

            with patch.object(storage, "mark_team_role_runtime_release_requested", side_effect=_wrapped):
                status = service.release_busy(team_role_id=team_role_id, release_reason="response_sent")

            self.assertEqual(status.status, "busy")
            self.assertTrue(observed_tx_depths)
            self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    async def test_group_mention_succeeds_with_write_uow_guard_enabled(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "ltc62_group.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9301, "grp")
                role = storage.upsert_role(
                    role_name="worker",
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)

            role_catalog_dir = Path(td) / "roles_catalog"
            role_catalog_dir.mkdir(parents=True, exist_ok=True)
            (role_catalog_dir / "worker.json").write_text(
                '{"role_name":"worker","description":"d","base_system_prompt":"sp","extra_instruction":"ei","llm_model":null,"is_active":true}',
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(role_catalog_dir)
            storage.attach_role_catalog(role_catalog)
            storage.enable_write_uow_guard()

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["ok from worker"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=PendingStore(db_path),
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=10),
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=3,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            result = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=group.group_id,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="@worker ping",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=11,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=False,
            )

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            self.assertIn("ok from worker", "\n".join(bot.sent))


if __name__ == "__main__":
    unittest.main()
