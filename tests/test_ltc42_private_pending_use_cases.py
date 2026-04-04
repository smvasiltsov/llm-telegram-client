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

from app.application.use_cases.private_pending_field import (
    build_pending_field_replay_plan,
    delete_provider_user_field_from_pending_state,
    normalize_pending_field_value,
    set_provider_user_field_from_pending_state,
    validate_pending_field_value,
)
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


class LTC42PrivatePendingUseCaseTests(unittest.TestCase):
    def test_normalize_pending_field_value_empty(self) -> None:
        res = normalize_pending_field_value({"key": "working_dir"}, "   ")
        self.assertTrue(res.is_error)
        self.assertIsNotNone(res.error)
        assert res.error is not None
        self.assertIn("не может быть пустым", res.error.message)

    def test_normalize_pending_field_value_auth_token_cookie(self) -> None:
        res = normalize_pending_field_value({"key": "auth_token"}, "cookie: sessionid=abc123; path=/")
        self.assertTrue(res.is_ok)
        self.assertEqual(res.value, "abc123")

    def test_build_pending_field_replay_plan_actions(self) -> None:
        state = {"provider_id": "skills", "key": "root_dir", "role_id": 10, "team_id": 1}
        same = {"provider_id": "skills", "key": "root_dir", "role_id": 10, "team_id": 1}
        other = {"provider_id": "skills", "key": "root_dir", "role_id": None, "team_id": None}

        p1 = build_pending_field_replay_plan(
            state=state,
            replay_pending_state=same,
            pending_msg_exists=True,
            replay_attempts=1,
            max_retries=2,
        )
        self.assertEqual(p1.action, "request_again")

        p2 = build_pending_field_replay_plan(
            state=state,
            replay_pending_state=same,
            pending_msg_exists=True,
            replay_attempts=3,
            max_retries=2,
        )
        self.assertEqual(p2.action, "suppress_and_drop")

        p3 = build_pending_field_replay_plan(
            state=other,
            replay_pending_state=state,
            pending_msg_exists=True,
            replay_attempts=0,
            max_retries=2,
        )
        self.assertEqual(p3.action, "noop")
        self.assertTrue(p3.should_delete_saved_value)

        p4 = build_pending_field_replay_plan(
            state=other,
            replay_pending_state=None,
            pending_msg_exists=False,
            replay_attempts=0,
            max_retries=2,
        )
        self.assertEqual(p4.action, "missing_pending_message")

        p5 = build_pending_field_replay_plan(
            state=other,
            replay_pending_state=None,
            pending_msg_exists=True,
            replay_attempts=0,
            max_retries=2,
        )
        self.assertEqual(p5.action, "restore_and_request")

    def test_set_delete_provider_user_field_from_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-3001, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)

            state = {
                "provider_id": "skills",
                "key": "root_dir",
                "role_id": role.role_id,
                "team_id": team_id,
            }
            set_provider_user_field_from_pending_state(storage, state, "/tmp")
            self.assertEqual(
                storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id),
                "/tmp",
            )
            delete_provider_user_field_from_pending_state(storage, state)
            self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id))

    def test_validate_pending_field_value_for_root_dir(self) -> None:
        state = {"key": "root_dir"}
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(validate_pending_field_value(state, td))
        err = validate_pending_field_value(state, "/path/that/does/not/exist")
        self.assertIsInstance(err, str)


class LTC42PrivatePendingHandlerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_handler_pending_field_empty_value_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            pending_fields = PendingUserFieldStore(db_path)
            pending_store = PendingStore(db_path)

            pending_fields.save(
                telegram_user_id=42,
                provider_id="skills",
                key="root_dir",
                role_id=1,
                prompt="Введите root_dir",
                chat_id=-1001,
                team_id=1,
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
            update = _FakeUpdate(42, "   ")

            await handle_private_message(update, context)  # type: ignore[arg-type]
            self.assertIn("Значение не может быть пустым. Попробуй ещё раз.", update.message.replies)


if __name__ == "__main__":
    unittest.main()
