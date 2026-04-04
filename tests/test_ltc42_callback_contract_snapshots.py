from __future__ import annotations

import importlib
import sys
import types
import unittest

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


class _InlineKeyboardButton:
    def __init__(self, text: str, callback_data: str | None = None, **kwargs) -> None:  # noqa: ANN003
        self.text = text
        self.callback_data = callback_data
        self.kwargs = kwargs


class _InlineKeyboardMarkup:
    def __init__(self, inline_keyboard):  # noqa: ANN001
        self.inline_keyboard = inline_keyboard


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


if not hasattr(telegram_module, "CallbackQuery"):
    telegram_module.CallbackQuery = _Dummy
if not hasattr(telegram_module, "Update"):
    telegram_module.Update = _Dummy
if not hasattr(telegram_module, "WebAppInfo"):
    telegram_module.WebAppInfo = _Dummy
telegram_module.InlineKeyboardButton = _InlineKeyboardButton
telegram_module.InlineKeyboardMarkup = _InlineKeyboardMarkup
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

from app.handlers import callbacks as callbacks_module

callbacks_module = importlib.reload(callbacks_module)
_master_defaults_keyboard = callbacks_module._master_defaults_keyboard
_role_actions_keyboard = callbacks_module._role_actions_keyboard


class CallbackContractSnapshotTests(unittest.TestCase):
    def test_role_actions_keyboard_callback_data_snapshot(self) -> None:
        markup = _role_actions_keyboard(group_id=10, role_id=20, enabled=True, mode="normal")
        actual = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        expected = [
            "act:toggle_enabled:10:20",
            "act:set_mode_orchestrator:10:20",
            "act:skills:10:20",
            "act:prepost_processing:10:20",
            "act:set_prompt:10:20",
            "act:set_suffix:10:20",
            "act:set_reply_prefix:10:20",
            "act:set_model:10:20",
            "act:master_defaults:10:20",
            "act:lock_groups:10:20",
            "act:rename_role:10:20",
            "act:reset_session:10:20",
            "act:delete_role:10:20",
            "grp:10",
        ]
        self.assertEqual(actual, expected)

    def test_role_actions_keyboard_mode_orchestrator_contract(self) -> None:
        markup = _role_actions_keyboard(group_id=5, role_id=6, enabled=False, mode="orchestrator")
        actual = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertIn("act:set_mode_normal:5:6", actual)
        self.assertIn("act:toggle_enabled:5:6", actual)

    def test_master_defaults_keyboard_callback_data_snapshot(self) -> None:
        markup = _master_defaults_keyboard(group_id=7, role_id=8)
        actual = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        expected = [
            "act:master_set_prompt:7:8",
            "act:master_clear_prompt:7:8",
            "act:master_set_suffix:7:8",
            "act:master_clear_suffix:7:8",
            "act:master_set_model:7:8",
            "act:master_clear_model:7:8",
            "role:7:8",
        ]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
