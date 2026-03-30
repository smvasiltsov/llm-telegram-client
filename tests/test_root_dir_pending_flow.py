from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    telegram_constants_module = types.ModuleType("telegram.constants")
    telegram_error_module = types.ModuleType("telegram.error")
    class _BadRequest(Exception):
        pass
    telegram_module.InlineKeyboardButton = object
    telegram_module.InlineKeyboardMarkup = object
    telegram_module.WebAppInfo = object
    telegram_module.Update = object
    telegram_ext_module.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
    telegram_constants_module.ParseMode = SimpleNamespace(HTML="HTML", MARKDOWN="MARKDOWN")
    telegram_error_module.BadRequest = _BadRequest
    telegram_module.ext = telegram_ext_module
    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.ext"] = telegram_ext_module
    sys.modules["telegram.constants"] = telegram_constants_module
    sys.modules["telegram.error"] = telegram_error_module

from app.handlers.messages_common import _handle_missing_user_field
from app.handlers.messages_private import handle_private_message
from app.llm_providers import ProviderUserField
from app.llm_router import MissingUserField
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.role_catalog import RoleCatalog
from app.storage import Storage


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class _FakeMessage:
    def __init__(self, text: str, message_id: int = 1) -> None:
        self.text = text
        self.message_id = message_id
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class _FakeChat:
    def __init__(self, chat_id: int, chat_type: str = "private") -> None:
        self.id = chat_id
        self.type = chat_type


class _FakeUser:
    def __init__(self, user_id: int, username: str = "u") -> None:
        self.id = user_id
        self.username = username


class _FakeUpdate:
    def __init__(self, user_id: int, text: str) -> None:
        self.effective_user = _FakeUser(user_id)
        self.effective_chat = _FakeChat(user_id, "private")
        self.message = _FakeMessage(text)


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

    async def test_root_dir_replay_repeat_budget_keeps_saved_value(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-1001, "g")
            role = storage.upsert_role(
                role_name="fs_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)

            pending = PendingStore(db_path)
            pending_fields = PendingUserFieldStore(db_path)
            pending.save(
                telegram_user_id=42,
                chat_id=group.group_id,
                team_id=team_id,
                message_id=100,
                role_name=role.public_name(),
                content="list files",
                reply_text=None,
            )
            pending_fields.save(
                telegram_user_id=42,
                provider_id="skills",
                key="root_dir",
                role_id=role.role_id,
                prompt="Введите root_dir",
                chat_id=group.group_id,
                team_id=team_id,
            )
            bot = _FakeBot()
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(
                storage=storage,
                role_catalog=RoleCatalog.load(catalog_dir),
                pending_store=pending,
                pending_user_fields=pending_fields,
                pending_prompts={},
                pending_role_ops={},
                pending_bash_auth={},
                tools_bash_password="",
                tool_service=None,
                bash_cwd_by_user={},
                private_buffer=None,
                auth_service=None,
                pending_replay_attempts={},
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _fake_replay(_user_id: int, _context: object) -> bool:
                pending_fields.save(
                    telegram_user_id=42,
                    provider_id="skills",
                    key="root_dir",
                    role_id=role.role_id,
                    prompt="Введите root_dir",
                    chat_id=group.group_id,
                    team_id=team_id,
                )
                return False

            with patch("app.handlers.messages_private._process_pending_message_for_user", _fake_replay):
                update1 = _FakeUpdate(42, td)
                await handle_private_message(update1, context)  # type: ignore[arg-type]
                update2 = _FakeUpdate(42, td)
                await handle_private_message(update2, context)  # type: ignore[arg-type]
                update3 = _FakeUpdate(42, td)
                await handle_private_message(update3, context)  # type: ignore[arg-type]

            team_value = storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id)
            self.assertEqual(team_value, td)
            self.assertIsNone(pending.peek_record(42))
            self.assertIsNone(pending_fields.get(42))
            self.assertEqual(len(bot.sent), 2)
            self.assertTrue(any("Введите root_dir" in text for _, text in bot.sent))
            self.assertTrue(any("нескольких попыток" in text for text in update3.message.replies))

    async def test_role_scoped_replay_repeat_budget_keeps_value_for_non_root_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-1002, "g")
            role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)

            pending = PendingStore(db_path)
            pending_fields = PendingUserFieldStore(db_path)
            pending.save(
                telegram_user_id=77,
                chat_id=group.group_id,
                team_id=team_id,
                message_id=200,
                role_name=role.public_name(),
                content="run task",
                reply_text=None,
            )
            pending_fields.save(
                telegram_user_id=77,
                provider_id="provider",
                key="working_dir",
                role_id=role.role_id,
                prompt="Введите working_dir",
                chat_id=group.group_id,
                team_id=team_id,
            )
            bot = _FakeBot()
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(
                storage=storage,
                role_catalog=RoleCatalog.load(catalog_dir),
                pending_store=pending,
                pending_user_fields=pending_fields,
                pending_prompts={},
                pending_role_ops={},
                pending_bash_auth={},
                tools_bash_password="",
                tool_service=None,
                bash_cwd_by_user={},
                private_buffer=None,
                auth_service=None,
                pending_replay_attempts={},
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _fake_replay(_user_id: int, _context: object) -> bool:
                pending_fields.save(
                    telegram_user_id=77,
                    provider_id="provider",
                    key="working_dir",
                    role_id=role.role_id,
                    prompt="Введите working_dir",
                    chat_id=group.group_id,
                    team_id=team_id,
                )
                return False

            with patch("app.handlers.messages_private._process_pending_message_for_user", _fake_replay):
                update1 = _FakeUpdate(77, td)
                await handle_private_message(update1, context)  # type: ignore[arg-type]
                update2 = _FakeUpdate(77, td)
                await handle_private_message(update2, context)  # type: ignore[arg-type]
                update3 = _FakeUpdate(77, td)
                await handle_private_message(update3, context)  # type: ignore[arg-type]

            team_value = storage.get_provider_user_value_by_team_role("provider", "working_dir", team_role_id)
            self.assertEqual(team_value, td)
            self.assertIsNone(pending.peek_record(77))
            self.assertIsNone(pending_fields.get(77))
            self.assertEqual(len(bot.sent), 2)
            self.assertTrue(any("Введите working_dir" in text for _, text in bot.sent))
            self.assertTrue(any("нескольких попыток" in text for text in update3.message.replies))

if __name__ == "__main__":
    unittest.main()
