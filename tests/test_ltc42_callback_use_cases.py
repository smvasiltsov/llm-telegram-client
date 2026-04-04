from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

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
    MARKDOWN = "MARKDOWN"


class _BadRequest(Exception):
    pass


if not hasattr(telegram_module, "Update"):
    telegram_module.Update = _Dummy
if not hasattr(telegram_module, "CallbackQuery"):
    telegram_module.CallbackQuery = _Dummy
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

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

from app.application.use_cases.callback_role_actions import RoleActionRequest, execute_role_action
from app.handlers.callbacks import _handle_action
from app.role_catalog import RoleCatalog
from app.storage import Storage


class CallbackRoleActionsUseCaseTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        db_path = Path(td.name) / "test.sqlite3"
        storage = Storage(db_path)
        group = storage.upsert_group(-9101, "g")
        role = storage.upsert_role(
            role_name="role_a",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        storage.ensure_group_role(group.group_id, role.role_id)
        return storage, group.group_id, role.role_id, int(group.team_id or 0)

    def test_execute_role_action_toggle_enabled(self) -> None:
        storage, group_id, role_id, team_id = self._bootstrap()
        state_before = storage.get_team_role(team_id, role_id)
        self.assertTrue(state_before.enabled)

        result = execute_role_action(
            storage,
            RoleActionRequest(action="toggle_enabled", group_id=group_id, role_id=role_id),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertFalse(result.value.state.enabled)

    def test_execute_role_action_set_mode_orchestrator_returns_previous(self) -> None:
        storage, group_id, role_id, _ = self._bootstrap()
        role_b = storage.upsert_role(
            role_name="role_b",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        storage.ensure_group_role(group_id, role_b.role_id)
        storage.set_group_role_mode(group_id, role_b.role_id, "orchestrator")

        result = execute_role_action(
            storage,
            RoleActionRequest(action="set_mode_orchestrator", group_id=group_id, role_id=role_id),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.state.mode, "orchestrator")
        self.assertEqual(result.value.previous_orchestrator_role_id, role_b.role_id)


class _FakeQuery:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=-9101))
        self.edits: list[str] = []
        self.answers: list[str | None] = []

    async def edit_message_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.edits.append(text)

    async def answer(self, text: str | None = None) -> None:
        self.answers.append(text)


class CallbackHandlerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_action_toggle_enabled_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            group = storage.upsert_group(-9101, "g")
            role = storage.upsert_role(
                role_name="role_a",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            runtime = SimpleNamespace(
                storage=storage,
                role_catalog=RoleCatalog.load(catalog_dir),
                pending_prompts={},
                pending_role_ops={},
            )
            query = _FakeQuery(user_id=1)
            handled = await _handle_action(
                query,
                f"act:toggle_enabled:{group.group_id}:{role.role_id}",
                context=SimpleNamespace(bot=SimpleNamespace(send_message=lambda **kwargs: None)),
                storage=storage,
                runtime=runtime,
            )
            self.assertTrue(handled)
            self.assertTrue(any("Роль отключена." in text for text in query.edits))
            self.assertEqual(len(query.answers), 1)


if __name__ == "__main__":
    unittest.main()
