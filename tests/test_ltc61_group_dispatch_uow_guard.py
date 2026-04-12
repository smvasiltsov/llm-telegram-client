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


class LTC61GroupDispatchUowGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_dispatch_ensures_team_role_inside_transaction(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "ltc61_group.sqlite3"
            storage = Storage(db_path)
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9201, "grp")
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
                role_runtime_status_service=status_service,
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=3,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            ensured_calls: list[tuple[int, int]] = []
            original_ensure_team_role = storage.ensure_team_role

            def _assert_tx_and_delegate(team_id: int, role_id: int):
                if storage._tx_depth <= 0:
                    raise AssertionError("ensure_team_role called outside transaction")
                ensured_calls.append((team_id, role_id))
                return original_ensure_team_role(team_id, role_id)

            with patch.object(storage, "ensure_team_role", side_effect=_assert_tx_and_delegate):
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
            self.assertTrue(bot.sent)
            self.assertIn("ok from worker", "\n".join(bot.sent))
            self.assertTrue(ensured_calls)
            self.assertIsNotNone(storage.resolve_team_role_id(group.team_id or 0, role.role_id))


if __name__ == "__main__":
    unittest.main()
