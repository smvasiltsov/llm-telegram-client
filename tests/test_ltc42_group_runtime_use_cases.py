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

from app.application.contracts.result import Result
from app.application.use_cases.group_runtime import GroupBufferPlan, GroupFlushInput, GroupFlushPlan, build_group_flush_plan, prepare_group_buffer_plan
from app.handlers import messages_group
from app.role_catalog import RoleCatalog
from app.storage import Storage


def _write_role_json(root: Path, role_name: str) -> None:
    payload = (
        "{\n"
        f'  "schema_version": 1,\n  "role_name": "{role_name}",\n'
        '  "description": "d",\n  "base_system_prompt": "sp",\n'
        '  "extra_instruction": "ei",\n  "llm_model": null,\n  "is_active": true\n}\n'
    )
    (root / f"{role_name}.json").write_text(payload, encoding="utf-8")


class _FakeCipher:
    def decrypt(self, encrypted_token: str) -> str:
        return f"dec:{encrypted_token}"


class GroupRuntimeUseCaseTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, SimpleNamespace, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        db_path = Path(td.name) / "test.sqlite3"
        root = Path(td.name) / "roles_catalog"
        root.mkdir(parents=True, exist_ok=True)

        storage = Storage(db_path)
        group = storage.upsert_group(-11001, "team")
        role = storage.upsert_role(
            role_name="dev",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        _write_role_json(root, "dev")
        storage.ensure_group_role(group.group_id, role.role_id)
        runtime = SimpleNamespace(
            owner_user_id=101,
            bot_username="mybot",
            require_bot_mention=True,
            role_catalog=RoleCatalog.load(root),
        )
        return storage, runtime, group.group_id, role.role_id

    def test_prepare_group_buffer_plan_non_owner_is_ignored(self) -> None:
        storage, runtime, chat_id, _ = self._bootstrap()
        result = prepare_group_buffer_plan(
            storage=storage,
            runtime=runtime,
            chat_id=chat_id,
            chat_title="team",
            user_id=999,
            text="@mybot @dev hi",
        )
        self.assertTrue(result.is_ok)
        self.assertIsNotNone(result.value)
        assert result.value is not None
        self.assertFalse(result.value.should_process)
        self.assertFalse(result.value.should_start)

    def test_prepare_group_buffer_plan_orchestrator_forces_start(self) -> None:
        storage, runtime, chat_id, role_id = self._bootstrap()
        orch = storage.upsert_role(
            role_name="orch",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        _write_role_json(runtime.role_catalog.root_dir, "orch")
        storage.ensure_group_role(chat_id, orch.role_id)
        storage.set_group_role_mode(chat_id, orch.role_id, "orchestrator")

        result = prepare_group_buffer_plan(
            storage=storage,
            runtime=runtime,
            chat_id=chat_id,
            chat_title="team",
            user_id=runtime.owner_user_id,
            text="text without mention",
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertTrue(result.value.should_process)
        self.assertTrue(result.value.should_start)
        self.assertEqual(result.value.orchestrator_role_name, "orch")
        self.assertIn("dev", result.value.role_names)
        self.assertIn("orch", result.value.role_names)

    def test_build_group_flush_plan_send_hint_when_content_empty(self) -> None:
        storage, runtime, chat_id, _ = self._bootstrap()
        result = build_group_flush_plan(
            storage=storage,
            runtime=runtime,
            data=GroupFlushInput(
                chat_id=chat_id,
                user_id=runtime.owner_user_id,
                combined_text="@mybot @dev",
                reply_text=None,
                first_message_id=10,
                bot_username=runtime.bot_username,
                owner_user_id=runtime.owner_user_id,
                require_bot_mention=True,
            ),
            roles_require_auth_fn=lambda **_: False,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "send_hint")

    def test_build_group_flush_plan_requests_token_when_required(self) -> None:
        storage, runtime, chat_id, _ = self._bootstrap()
        result = build_group_flush_plan(
            storage=storage,
            runtime=runtime,
            data=GroupFlushInput(
                chat_id=chat_id,
                user_id=runtime.owner_user_id,
                combined_text="@mybot @dev hello",
                reply_text="rt",
                first_message_id=11,
                bot_username=runtime.bot_username,
                owner_user_id=runtime.owner_user_id,
                require_bot_mention=True,
            ),
            roles_require_auth_fn=lambda **_: True,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "request_token")
        self.assertEqual(result.value.role_name_for_pending, "dev")
        self.assertEqual(result.value.content_for_pending, "hello")

    def test_build_group_flush_plan_dispatch_chain_with_decrypted_token(self) -> None:
        storage, runtime, chat_id, _ = self._bootstrap()
        storage.upsert_user(runtime.owner_user_id, "owner")
        storage.upsert_auth_token(runtime.owner_user_id, "enc-token")

        result = build_group_flush_plan(
            storage=storage,
            runtime=runtime,
            data=GroupFlushInput(
                chat_id=chat_id,
                user_id=runtime.owner_user_id,
                combined_text="@mybot @dev hello",
                reply_text=None,
                first_message_id=12,
                bot_username=runtime.bot_username,
                owner_user_id=runtime.owner_user_id,
                require_bot_mention=True,
            ),
            roles_require_auth_fn=lambda **_: False,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "dispatch_chain")
        self.assertEqual(result.value.session_token, "dec:enc-token")
        self.assertEqual(result.value.role_name_for_pending, "dev")


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append((chat_id, text))


class _FakeMessage:
    def __init__(self, message_id: int, text: str, reply_text: str | None = None) -> None:
        self.message_id = message_id
        self.content = text
        self.reply_text = reply_text


class _FakeBuffer:
    def __init__(self, items: list[_FakeMessage]) -> None:
        self._items = items

    async def wait_and_collect(self, chat_id: int, user_id: int):  # noqa: ANN001
        return list(self._items)


class GroupHandlerSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_flush_buffered_hint_text_contract(self) -> None:
        runtime = SimpleNamespace(
            message_buffer=_FakeBuffer([_FakeMessage(100, "@mybot @dev")]),
            storage=SimpleNamespace(),
            pending_store=SimpleNamespace(),
            owner_user_id=1,
            bot_username="mybot",
            require_bot_mention=True,
            cipher=_FakeCipher(),
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=_FakeBot())

        with patch(
            "app.handlers.messages_group.build_group_flush_plan",
            return_value=Result.ok(GroupFlushPlan(action="send_hint", team_id=1)),
        ):
            await messages_group._flush_buffered(-11001, 1, context)  # type: ignore[arg-type]

        self.assertEqual(context.bot.sent, [(-11001, "Напиши сообщение после роли.")])

    async def test_handle_group_buffered_uses_prepare_plan_start_flag(self) -> None:
        class _Chat:
            id = -22001
            title = "team"
            type = "group"

        class _User:
            id = 7
            username = "u"
            is_bot = False

        class _Msg:
            text = "hello"
            message_id = 77
            reply_to_message = None

        class _Buffer:
            def __init__(self) -> None:
                self.start_values: list[bool] = []

            async def add(self, chat_id: int, user_id: int, message_id: int, content: str, start: bool, reply_text=None) -> bool:  # noqa: ANN001
                self.start_values.append(start)
                return False

        runtime = SimpleNamespace(
            storage=SimpleNamespace(),
            message_buffer=_Buffer(),
            owner_user_id=7,
            bot_username="mybot",
            require_bot_mention=True,
        )
        update = SimpleNamespace(effective_chat=_Chat(), effective_user=_User(), message=_Msg())
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=_FakeBot())

        with patch(
            "app.handlers.messages_group.prepare_group_buffer_plan",
            return_value=Result.ok(
                GroupBufferPlan(
                    should_process=True,
                    should_start=False,
                    team_id=1,
                    role_names=("dev",),
                    orchestrator_role_name=None,
                )
            ),
        ):
            await messages_group.handle_group_buffered(update, context)  # type: ignore[arg-type]

        self.assertEqual(runtime.message_buffer.start_values, [False])


if __name__ == "__main__":
    unittest.main()
