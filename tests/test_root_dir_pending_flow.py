from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

if "telegram" not in sys.modules:
    telegram_module = types.ModuleType("telegram")
    telegram_ext_module = types.ModuleType("telegram.ext")
    telegram_module.InlineKeyboardButton = object
    telegram_module.InlineKeyboardMarkup = object
    telegram_module.Update = object
    telegram_ext_module.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
    telegram_module.ext = telegram_ext_module
    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.ext"] = telegram_ext_module

from app.handlers.messages_common import _handle_missing_user_field
from app.llm_providers import ProviderUserField
from app.llm_router import MissingUserField
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class RootDirPendingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_user_field_prompt_is_sent_once_for_same_pending_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            pending = PendingStore(db_path)
            pending_fields = PendingUserFieldStore(db_path)
            bot = _FakeBot()
            runtime = SimpleNamespace(pending_store=pending, pending_user_fields=pending_fields)
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)
            exc = MissingUserField(
                "skills",
                ProviderUserField(
                    key="root_dir",
                    prompt="Введите root_dir",
                    scope="role",
                ),
                role_id=10,
            )

            await _handle_missing_user_field(
                user_id=42,
                chat_id=-1001,
                team_id=1,
                message_id=11,
                role_name="fs_role",
                content="msg1",
                reply_text=None,
                exc=exc,
                context=context,  # type: ignore[arg-type]
            )
            await _handle_missing_user_field(
                user_id=42,
                chat_id=-1001,
                team_id=1,
                message_id=12,
                role_name="fs_role",
                content="msg2",
                reply_text=None,
                exc=exc,
                context=context,  # type: ignore[arg-type]
            )

            self.assertEqual(len(bot.sent), 1)
            self.assertEqual(bot.sent[0][0], 42)
            self.assertIn("root_dir", bot.sent[0][1])

if __name__ == "__main__":
    unittest.main()
