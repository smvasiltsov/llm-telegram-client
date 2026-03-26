from __future__ import annotations

import sys
import types
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

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
    telegram_module.WebAppInfo = _Dummy

    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.constants"] = telegram_constants
    sys.modules["telegram.error"] = telegram_error
    sys.modules["telegram.ext"] = telegram_ext

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

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
        retries: int = 2,
    ) -> str:
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


class LTC18PipelineBusySemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_chain_releases_busy_after_response_delivery(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_release.sqlite3")
            status_service = RoleRuntimeStatusService(storage)
            group = storage.upsert_group(-1001, "g")
            role = storage.upsert_role(
                role_name="busy_release_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = int(storage.resolve_team_role_id(group.team_id or 0, role.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(team_role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "busy_release_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "busy_release_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["done"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            result = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="hello",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=10,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            status = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status)
            self.assertEqual(status.status if status else None, "free")
            self.assertEqual(status.last_release_reason if status else None, "response_sent")
            self.assertTrue(any("done" in item for item in bot.sent))

    async def test_run_chain_returns_busy_message_when_lock_group_blocked(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_block.sqlite3")
            status_service = RoleRuntimeStatusService(storage)

            group_a = storage.upsert_group(-2001, "a")
            role_a = storage.upsert_role(
                role_name="role_a",
                description="a",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group_a.group_id, role_a.role_id)
            tr_a = int(storage.resolve_team_role_id(group_a.team_id or 0, role_a.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(tr_a)

            group_b = storage.upsert_group(-2002, "b")
            role_b = storage.upsert_role(
                role_name="role_b",
                description="b",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group_b.group_id, role_b.role_id)
            tr_b = int(storage.resolve_team_role_id(group_b.team_id or 0, role_b.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(tr_b)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "role_a.json").write_text(
                json.dumps(
                    {
                        "role_name": "role_a",
                        "description": "a",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (catalog_dir / "role_b.json").write_text(
                json.dumps(
                    {
                        "role_name": "role_b",
                        "description": "b",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            lock_group = storage.create_role_lock_group("shared_pool")
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_a)
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_b)
            status_service.acquire_busy(
                team_role_id=tr_a,
                busy_request_id="req-a",
                busy_owner_user_id=1,
                busy_origin="group",
                preview_text="blocked by A",
                preview_source="user",
            )

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["must-not-be-used"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            result = await run_chain(
                context=context,
                team_id=group_b.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role_b],
                user_text="hello",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=10,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            status_b = storage.get_team_role_runtime_status(tr_b)
            self.assertIsNotNone(status_b)
            self.assertEqual(status_b.status if status_b else None, "free")
            status_a = storage.get_team_role_runtime_status(tr_a)
            self.assertEqual(status_a.status if status_a else None, "busy")
            joined = "\n".join(bot.sent)
            self.assertIn("Роль сейчас занята", joined)
            self.assertIn("Текущая задача: blocked by A", joined)

    async def test_run_chain_honors_free_transition_delay(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_delay.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=120)
            group = storage.upsert_group(-3001, "g")
            role = storage.upsert_role(
                role_name="busy_delay_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = int(storage.resolve_team_role_id(group.team_id or 0, role.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(team_role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "busy_delay_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "busy_delay_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["done-1", "done-2"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            first = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="hello",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=10,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )
            self.assertFalse(first.had_error)
            status_after_first = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status_after_first)
            self.assertEqual(status_after_first.status if status_after_first else None, "busy")
            self.assertEqual(status_after_first.free_release_reason_pending if status_after_first else None, "response_sent")

            second = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="second",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=11,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )
            self.assertFalse(second.had_error)
            joined = "\n".join(bot.sent)
            self.assertIn("Роль сейчас занята", joined)

            finalized = status_service.finalize_due_releases(now="2999-01-01T00:00:00+00:00")
            self.assertEqual(finalized, 1)
            third = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="third",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=12,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )
            self.assertFalse(third.had_error)
            self.assertTrue(any("done-2" in item for item in bot.sent))


if __name__ == "__main__":
    unittest.main()
