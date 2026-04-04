from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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

from app.handlers.callbacks import _handle_action, _role_skills_keyboard
from app.storage import Storage


class _FakeQuery:
    def __init__(self, user_id: int, chat_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))
        self.edits: list[str] = []
        self.answers: list[str | None] = []

    async def edit_message_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.edits.append(text)

    async def answer(self, text: str | None = None) -> None:
        self.answers.append(text)


class _FakeSkillsRegistry:
    def list_specs(self):
        return [SimpleNamespace(skill_id="fs_list_dir", name="List Dir", mode="rw")]

    def get(self, skill_id: str):
        for spec in self.list_specs():
            if spec.skill_id == skill_id:
                return spec
        return None


class LTC65CallbacksUowGuardTests(unittest.IsolatedAsyncioTestCase):
    def _bootstrap(self) -> tuple[Storage, int, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc65.sqlite3")
        group = storage.upsert_group(-9651, "g")
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

    def test_role_skills_keyboard_ensure_team_role_runs_inside_transaction(self) -> None:
        storage, group_id, role_id, _team_id = self._bootstrap()
        runtime = SimpleNamespace(skills_registry=_FakeSkillsRegistry())
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original_ensure = storage.ensure_team_role

        def _wrapped(team_id: int, r_id: int):
            observed_tx_depths.append(storage._tx_depth)
            return original_ensure(team_id, r_id)

        with patch.object(storage, "ensure_team_role", side_effect=_wrapped):
            keyboard = _role_skills_keyboard(runtime, storage, group_id, role_id)

        self.assertIsNotNone(keyboard)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    async def test_private_skills_menu_open_succeeds_under_write_guard(self) -> None:
        storage, group_id, role_id, _team_id = self._bootstrap()
        storage.enable_write_uow_guard()
        runtime = SimpleNamespace(
            storage=storage,
            role_catalog=SimpleNamespace(get=lambda *_: None),
            pending_prompts={},
            pending_role_ops={},
            skills_registry=_FakeSkillsRegistry(),
            prepost_processing_registry=SimpleNamespace(list_specs=lambda: []),
        )
        query = _FakeQuery(user_id=1, chat_id=1)  # private chat
        handled = await _handle_action(
            query,
            f"act:skills:{group_id}:{role_id}",
            context=SimpleNamespace(bot=SimpleNamespace(send_message=lambda **kwargs: None)),
            storage=storage,
            runtime=runtime,
        )
        self.assertTrue(handled)
        self.assertTrue(any("Skills для роли" in text for text in query.edits))
        self.assertEqual(len(query.answers), 1)


if __name__ == "__main__":
    unittest.main()
