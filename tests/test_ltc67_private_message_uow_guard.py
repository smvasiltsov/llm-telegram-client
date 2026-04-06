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

telegram_module = sys.modules.get("telegram")
if telegram_module is None:
    telegram_module = types.ModuleType("telegram")
    sys.modules["telegram"] = telegram_module
telegram_ext_module = sys.modules.get("telegram.ext")
if telegram_ext_module is None:
    telegram_ext_module = types.ModuleType("telegram.ext")
    sys.modules["telegram.ext"] = telegram_ext_module
telegram_constants_module = sys.modules.get("telegram.constants")
if telegram_constants_module is None:
    telegram_constants_module = types.ModuleType("telegram.constants")
    sys.modules["telegram.constants"] = telegram_constants_module
telegram_error_module = sys.modules.get("telegram.error")
if telegram_error_module is None:
    telegram_error_module = types.ModuleType("telegram.error")
    sys.modules["telegram.error"] = telegram_error_module


class _BadRequest(Exception):
    pass


class _Dummy:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


if not hasattr(telegram_module, "InlineKeyboardButton"):
    telegram_module.InlineKeyboardButton = _Dummy
if not hasattr(telegram_module, "InlineKeyboardMarkup"):
    telegram_module.InlineKeyboardMarkup = _Dummy
if not hasattr(telegram_module, "WebAppInfo"):
    telegram_module.WebAppInfo = _Dummy
if not hasattr(telegram_module, "Update"):
    telegram_module.Update = _Dummy
if not hasattr(telegram_ext_module, "ContextTypes"):
    telegram_ext_module.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
if not hasattr(telegram_constants_module, "ParseMode"):
    telegram_constants_module.ParseMode = SimpleNamespace(HTML="HTML", MARKDOWN="MARKDOWN")
if not hasattr(telegram_error_module, "BadRequest"):
    telegram_error_module.BadRequest = _BadRequest
telegram_module.ext = telegram_ext_module

from app.handlers.messages_private import handle_private_message
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.role_catalog import RoleCatalog
from app.storage import Storage


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


class _FakeBot:
    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # noqa: ANN001
        return None


class LTC67PrivateMessageUowGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_upsert_user_runs_inside_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            storage.enable_write_uow_guard()
            pending_fields = PendingUserFieldStore(db_path)
            pending_store = PendingStore(db_path)
            runtime = SimpleNamespace(
                storage=storage,
                role_catalog=RoleCatalog.load(catalog_dir),
                pending_bash_auth={},
                tools_bash_password="",
                tool_service=None,
                bash_cwd_by_user={},
                pending_user_fields=pending_fields,
                pending_store=pending_store,
                pending_prompts={},
                pending_role_ops={},
                private_buffer=None,
                auth_service=None,
                provider_models=[],
                provider_registry={},
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=_FakeBot())
            update = _FakeUpdate(42, "hello")
            observed_tx_depths: list[int] = []
            original_upsert = storage.upsert_user

            def _wrapped(telegram_user_id: int, username: str | None = None):
                observed_tx_depths.append(storage._tx_depth)
                return original_upsert(telegram_user_id, username)

            with patch.object(storage, "upsert_user", side_effect=_wrapped):
                await handle_private_message(update, context)  # type: ignore[arg-type]

            self.assertTrue(observed_tx_depths)
            self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    async def test_private_root_dir_flow_succeeds_under_write_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            storage.enable_write_uow_guard()
            pending_fields = PendingUserFieldStore(db_path)
            pending_store = PendingStore(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-3101, "g")
                role = storage.upsert_role(
                    role_name="dev",
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)
            (catalog_dir / "dev.json").write_text(
                '{"role_name":"dev","description":"d","base_system_prompt":"sp","extra_instruction":"ei","llm_model":null,"is_active":true}',
                encoding="utf-8",
            )

            pending_fields.save(
                telegram_user_id=42,
                provider_id="skills",
                key="root_dir",
                role_id=role.role_id,
                prompt="Введите root_dir",
                chat_id=-3101,
                team_id=int(group.team_id or 0),
            )

            runtime = SimpleNamespace(
                storage=storage,
                role_catalog=RoleCatalog.load(catalog_dir),
                pending_bash_auth={},
                tools_bash_password="",
                tool_service=None,
                bash_cwd_by_user={},
                pending_user_fields=pending_fields,
                pending_store=pending_store,
                pending_prompts={},
                pending_role_ops={},
                private_buffer=None,
                auth_service=None,
                provider_models=[],
                provider_registry={},
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=_FakeBot())
            update = _FakeUpdate(42, td)

            await handle_private_message(update, context)  # type: ignore[arg-type]

            self.assertIn("Проверяю значение и пытаюсь ответить на сообщение из группы.", update.message.replies)
            self.assertIn("Нет ожидающего сообщения из группы. Отправь запрос в группу ещё раз.", update.message.replies)


if __name__ == "__main__":
    unittest.main()
