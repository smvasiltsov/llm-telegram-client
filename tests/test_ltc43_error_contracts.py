from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

if "telegram" not in sys.modules:
    telegram_module = types.ModuleType("telegram")
    telegram_ext = types.ModuleType("telegram.ext")

    class _InlineKeyboardButton:
        def __init__(self, text: str, callback_data: str | None = None, **kwargs) -> None:  # noqa: ANN003
            self.text = text
            self.callback_data = callback_data
            self.kwargs = kwargs

    class _InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):  # noqa: ANN001
            self.inline_keyboard = inline_keyboard

    class _ContextTypes:
        DEFAULT_TYPE = object

    class _Dummy:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    telegram_module.Update = _Dummy
    telegram_module.InlineKeyboardButton = _InlineKeyboardButton
    telegram_module.InlineKeyboardMarkup = _InlineKeyboardMarkup
    telegram_module.WebAppInfo = _Dummy
    telegram_ext.ContextTypes = _ContextTypes
    telegram_module.ext = telegram_ext

    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.ext"] = telegram_ext

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

from app.application.contracts import map_exception_to_error
from app.handlers.commands import handle_group_roles
from app.storage import Storage


class LTC43ErrorContractsTests(unittest.TestCase):
    def test_storage_role_not_found_contract(self) -> None:
        code, message, details, http_status, retryable = map_exception_to_error(ValueError("Role not found: dev"))
        self.assertEqual(code, "storage.not_found")
        self.assertEqual(http_status, 404)
        self.assertFalse(retryable)
        self.assertEqual(details, {"entity": "role", "cause": "not_found", "id": "dev"})
        self.assertEqual(message, "Role not found: dev")

    def test_storage_team_role_not_found_contract(self) -> None:
        text = "Team role not found: team_id=1 role_id=2"
        code, message, details, http_status, retryable = map_exception_to_error(ValueError(text))
        self.assertEqual(code, "storage.not_found")
        self.assertEqual(http_status, 404)
        self.assertFalse(retryable)
        self.assertEqual(details, {"entity": "team_role", "cause": "not_found", "id": "team_id=1 role_id=2"})
        self.assertEqual(message, text)

    def test_storage_team_not_found_contract(self) -> None:
        text = "Team not found: 77"
        code, message, details, http_status, retryable = map_exception_to_error(ValueError(text))
        self.assertEqual(code, "storage.not_found")
        self.assertEqual(http_status, 404)
        self.assertFalse(retryable)
        self.assertEqual(details, {"entity": "team", "cause": "not_found", "id": "77"})
        self.assertEqual(message, text)


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.replies.append(text)


class _FakeUpdate:
    def __init__(self, user_id: int) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()


class LTC43CommandsContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_group_roles_not_found_keeps_ux_and_maps_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            runtime = SimpleNamespace(storage=storage, owner_user_id=100)
            update = _FakeUpdate(user_id=100)
            context = SimpleNamespace(args=["123456"], application=SimpleNamespace(bot_data={"runtime": runtime}))

            await handle_group_roles(update, context)  # type: ignore[arg-type]
            self.assertIn("Группа не найдена.", update.message.replies)


if __name__ == "__main__":
    unittest.main()
