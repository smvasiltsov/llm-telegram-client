from __future__ import annotations

import asyncio
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
    telegram_module.__path__ = []
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


class _ContextTypes:
    DEFAULT_TYPE = object


class _ParseMode:
    HTML = "HTML"
    MARKDOWN = "MARKDOWN"


class _Dummy:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _BadRequest(Exception):
    pass


if not hasattr(telegram_ext, "ContextTypes"):
    telegram_ext.ContextTypes = _ContextTypes
if not hasattr(telegram_constants, "ParseMode"):
    telegram_constants.ParseMode = _ParseMode
if not hasattr(telegram_error, "BadRequest"):
    telegram_error.BadRequest = _BadRequest
if not hasattr(telegram_module, "InlineKeyboardButton"):
    telegram_module.InlineKeyboardButton = _Dummy
if not hasattr(telegram_module, "InlineKeyboardMarkup"):
    telegram_module.InlineKeyboardMarkup = _Dummy
if not hasattr(telegram_module, "WebAppInfo"):
    telegram_module.WebAppInfo = _Dummy
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

from app.interfaces.telegram_runtime_client import LegacyRuntimeClient, ThinRuntimeClient, resolve_runtime_client
from app.llm_providers import ProviderConfig, ProviderUserField
from app.models import Role
from app.pending_store import PendingStore
from app.pending_user_fields import PendingUserFieldStore
from app.storage import Storage


class LTC87TelegramRuntimeClientTests(unittest.TestCase):
    def test_resolve_runtime_client_uses_runtime_flag_default_true(self) -> None:
        bot_data = {"runtime": SimpleNamespace(telegram_thin_client_enabled=True)}
        client = resolve_runtime_client(bot_data)
        self.assertIsInstance(client, ThinRuntimeClient)

    def test_resolve_runtime_client_supports_legacy_fallback_flag(self) -> None:
        bot_data = {"runtime": SimpleNamespace(telegram_thin_client_enabled=False)}
        client = resolve_runtime_client(bot_data)
        self.assertIsInstance(client, LegacyRuntimeClient)

    def test_resolve_runtime_client_prefers_injected_runtime_client(self) -> None:
        custom_client = object()
        custom_client = SimpleNamespace(execute_run_chain=lambda **_: None)
        bot_data = {
            "runtime": SimpleNamespace(telegram_thin_client_enabled=False),
            "runtime_client": custom_client,
        }
        client = resolve_runtime_client(bot_data)
        self.assertIs(client, custom_client)


class LTC87TelegramRuntimeClientThinPendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_thin_client_schedules_async_answer_delivery_on_poll_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-8870, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="codex-api:default",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            runtime = SimpleNamespace(
                storage=storage,
                pending_store=PendingStore(db_path),
                pending_user_fields=PendingUserFieldStore(db_path),
                telegram_api_base_url="http://127.0.0.1:8080",
                telegram_api_timeout_sec=1,
                telegram_api_answer_timeout_sec=3,
                telegram_api_answer_poll_interval_sec=0.1,
                owner_user_id=700,
                llm_router=SimpleNamespace(provider_id_for_model=lambda _m: "codex-api"),
                provider_registry={"codex-api": ProviderConfig(
                    provider_id="codex-api",
                    label="Codex API",
                    base_url="http://127.0.0.1:8002",
                    tls_ca_cert_path=None,
                    adapter="generic",
                    capabilities={},
                    auth_mode="none",
                    endpoints={},
                    models=[],
                    history_enabled=False,
                    history_limit=None,
                    user_fields={},
                )},
            )

            class _FakeBot:
                def __init__(self) -> None:
                    self.sent: list[tuple[int, str, int | None]] = []

                async def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
                    self.sent.append((chat_id, text, reply_to_message_id))

            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            class _Resp:
                def __init__(self, status_code: int, payload: object | None = None, text: str = "") -> None:
                    self.status_code = status_code
                    self._payload = payload
                    self.text = text

                def json(self):
                    return self._payload

            class _FakeClient:
                answer_calls = 0

                def __init__(self, *args, **kwargs) -> None:
                    _ = (args, kwargs)
                    self._question_id = "q-async-1"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    _ = (exc_type, exc, tb)
                    return False

                async def get(self, path: str, params=None, headers=None):
                    _ = (params, headers)
                    if path == f"/api/v1/teams/{team_id}/roles":
                        return _Resp(
                            200,
                            payload=[
                                {
                                    "team_role_id": team_role_id,
                                    "role_id": role.role_id,
                                    "working_dir": "/abs/work",
                                    "root_dir": None,
                                    "skills": [],
                                }
                            ],
                        )
                    if path == f"/api/v1/questions/{self._question_id}/answer":
                        _FakeClient.answer_calls += 1
                        if _FakeClient.answer_calls < 3:
                            return _Resp(409, payload={"message": "in_progress"})
                        return _Resp(200, payload={"text": "async ok"})
                    return _Resp(404, payload={})

                async def post(self, path: str, json=None, headers=None):
                    _ = (json, headers)
                    if path == "/api/v1/questions":
                        return _Resp(202, payload={"question": {"question_id": self._question_id}})
                    return _Resp(404, payload={})

            with patch("app.interfaces.telegram_runtime_client.httpx.AsyncClient", _FakeClient, create=True):
                client = ThinRuntimeClient()
                result = await client.execute_run_chain(
                    context=context,
                    team_id=team_id,
                    chat_id=group.group_id,
                    user_id=42,
                    session_token="",
                    roles=[Role(
                        role_id=role.role_id,
                        role_name=role.role_name,
                        description=role.description,
                        base_system_prompt=role.base_system_prompt,
                        extra_instruction=role.extra_instruction,
                        llm_model=role.llm_model,
                        is_active=True,
                    )],
                    user_text="test",
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=10,
                    is_all=False,
                    apply_plugins=True,
                    save_pending_on_unauthorized=True,
                    pending_role_name="dev",
                    allow_orchestrator_post_event=False,
                    chain_origin="pending",
                    correlation_id="cid-async",
                    operation="runtime.pending_replay",
                )

                self.assertTrue(result.is_ok)
                self.assertTrue(bool(result.value and result.value.completed))
                self.assertEqual(bot.sent, [])

                for _ in range(50):
                    if bot.sent:
                        break
                    await asyncio.sleep(0.05)

            self.assertTrue(any(text == "async ok" for _, text, _ in bot.sent))

    async def test_thin_client_requests_dm_for_missing_working_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-8871, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="codex-api:default",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            runtime = SimpleNamespace(
                storage=storage,
                pending_store=PendingStore(db_path),
                pending_user_fields=PendingUserFieldStore(db_path),
                telegram_api_base_url="http://127.0.0.1:8080",
                telegram_api_timeout_sec=5,
                owner_user_id=700,
                llm_router=SimpleNamespace(provider_id_for_model=lambda _m: "codex-api"),
                provider_registry={
                    "codex-api": ProviderConfig(
                        provider_id="codex-api",
                        label="Codex API",
                        base_url="http://127.0.0.1:8002",
                        tls_ca_cert_path=None,
                        adapter="generic",
                        capabilities={},
                        auth_mode="none",
                        endpoints={},
                        models=[],
                        history_enabled=False,
                        history_limit=None,
                        user_fields={
                            "working_dir": ProviderUserField(
                                key="working_dir",
                                prompt="Введите working_dir",
                                scope="role",
                            )
                        },
                    )
                },
            )

            class _FakeBot:
                def __init__(self) -> None:
                    self.sent: list[tuple[int, str]] = []

                async def send_message(self, chat_id: int, text: str) -> None:
                    self.sent.append((chat_id, text))

            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            class _Resp:
                def __init__(self, status_code: int, payload: object | None = None, text: str = "") -> None:
                    self.status_code = status_code
                    self._payload = payload
                    self.text = text

                def json(self):
                    return self._payload

            class _FakeClient:
                def __init__(self, *args, **kwargs) -> None:
                    _ = (args, kwargs)

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    _ = (exc_type, exc, tb)
                    return False

                async def get(self, path: str, params=None, headers=None):
                    _ = (params, headers)
                    if path == f"/api/v1/teams/{team_id}/roles":
                        return _Resp(
                            200,
                            payload=[
                                {
                                    "team_role_id": team_role_id,
                                    "role_id": role.role_id,
                                    "working_dir": None,
                                    "root_dir": None,
                                    "skills": [],
                                }
                            ],
                        )
                    return _Resp(404, payload={})

                async def post(self, path: str, json=None, headers=None):
                    raise AssertionError(f"post must not be called when missing field is detected: {path} {json} {headers}")

            with patch("app.interfaces.telegram_runtime_client.httpx.AsyncClient", _FakeClient, create=True):
                client = ThinRuntimeClient()
                result = await client.execute_run_chain(
                    context=context,
                    team_id=team_id,
                    chat_id=group.group_id,
                    user_id=42,
                    session_token="",
                    roles=[Role(
                        role_id=role.role_id,
                        role_name=role.role_name,
                        description=role.description,
                        base_system_prompt=role.base_system_prompt,
                        extra_instruction=role.extra_instruction,
                        llm_model=role.llm_model,
                        is_active=True,
                    )],
                    user_text="test",
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=10,
                    is_all=False,
                    apply_plugins=True,
                    save_pending_on_unauthorized=True,
                    pending_role_name="dev",
                    allow_orchestrator_post_event=False,
                    chain_origin="group",
                    correlation_id="cid-1",
                )
            self.assertTrue(result.is_ok)
            self.assertTrue(bool(result.value and result.value.pending_saved))
            state = runtime.pending_user_fields.get(42)
            self.assertIsNotNone(state)
            self.assertEqual((state or {}).get("key"), "working_dir")
            self.assertTrue(any(chat_id == 42 for chat_id, _ in bot.sent))

    async def test_thin_client_does_not_request_root_dir_without_fs_skill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-8872, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="codex-api:default",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            runtime = SimpleNamespace(
                storage=storage,
                pending_store=PendingStore(db_path),
                pending_user_fields=PendingUserFieldStore(db_path),
                telegram_api_base_url="http://127.0.0.1:8080",
                telegram_api_timeout_sec=5,
                owner_user_id=700,
                llm_router=SimpleNamespace(provider_id_for_model=lambda _m: "codex-api"),
                provider_registry={
                    "codex-api": ProviderConfig(
                        provider_id="codex-api",
                        label="Codex API",
                        base_url="http://127.0.0.1:8002",
                        tls_ca_cert_path=None,
                        adapter="generic",
                        capabilities={},
                        auth_mode="none",
                        endpoints={},
                        models=[],
                        history_enabled=False,
                        history_limit=None,
                        user_fields={},
                    )
                },
            )

            class _FakeBot:
                def __init__(self) -> None:
                    self.sent: list[tuple[int, str]] = []

                async def send_message(self, chat_id: int, text: str, reply_to_message_id: int | None = None) -> None:
                    _ = reply_to_message_id
                    self.sent.append((chat_id, text))

            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            class _Resp:
                def __init__(self, status_code: int, payload: object | None = None, text: str = "") -> None:
                    self.status_code = status_code
                    self._payload = payload
                    self.text = text

                def json(self):
                    return self._payload

            class _FakeClient:
                def __init__(self, *args, **kwargs) -> None:
                    _ = (args, kwargs)
                    self._question_id = "q-1"

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    _ = (exc_type, exc, tb)
                    return False

                async def get(self, path: str, params=None, headers=None):
                    _ = (params, headers)
                    if path == f"/api/v1/teams/{team_id}/roles":
                        return _Resp(
                            200,
                            payload=[
                                {
                                    "team_role_id": team_role_id,
                                    "role_id": role.role_id,
                                    "working_dir": "/abs/work",
                                    "root_dir": None,
                                    "skills": [{"id": "web.search"}],
                                }
                            ],
                        )
                    if path == f"/api/v1/questions/{self._question_id}/answer":
                        return _Resp(200, payload={"text": "ok"})
                    return _Resp(404, payload={})

                async def post(self, path: str, json=None, headers=None):
                    _ = (json, headers)
                    if path == "/api/v1/questions":
                        return _Resp(202, payload={"question": {"question_id": self._question_id}})
                    return _Resp(404, payload={})

            with patch("app.interfaces.telegram_runtime_client.httpx.AsyncClient", _FakeClient, create=True):
                client = ThinRuntimeClient()
                result = await client.execute_run_chain(
                    context=context,
                    team_id=team_id,
                    chat_id=group.group_id,
                    user_id=42,
                    session_token="",
                    roles=[Role(
                        role_id=role.role_id,
                        role_name=role.role_name,
                        description=role.description,
                        base_system_prompt=role.base_system_prompt,
                        extra_instruction=role.extra_instruction,
                        llm_model=role.llm_model,
                        is_active=True,
                    )],
                    user_text="test",
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=10,
                    is_all=False,
                    apply_plugins=True,
                    save_pending_on_unauthorized=True,
                    pending_role_name="dev",
                    allow_orchestrator_post_event=False,
                    chain_origin="group",
                    correlation_id="cid-2",
                )
            self.assertTrue(result.is_ok)
            self.assertFalse(bool(result.value and result.value.pending_saved))
            self.assertIsNone(runtime.pending_user_fields.get(42))
            self.assertTrue(any(chat_id == group.group_id for chat_id, _ in bot.sent))

    async def test_thin_client_requests_root_dir_for_fs_skill_id_payload(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-8873, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="codex-api:default",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            runtime = SimpleNamespace(
                storage=storage,
                pending_store=PendingStore(db_path),
                pending_user_fields=PendingUserFieldStore(db_path),
                telegram_api_base_url="http://127.0.0.1:8080",
                telegram_api_timeout_sec=5,
                owner_user_id=700,
                llm_router=SimpleNamespace(provider_id_for_model=lambda _m: "codex-api"),
                provider_registry={
                    "codex-api": ProviderConfig(
                        provider_id="codex-api",
                        label="Codex API",
                        base_url="http://127.0.0.1:8002",
                        tls_ca_cert_path=None,
                        adapter="generic",
                        capabilities={},
                        auth_mode="none",
                        endpoints={},
                        models=[],
                        history_enabled=False,
                        history_limit=None,
                        user_fields={},
                    )
                },
            )

            class _FakeBot:
                def __init__(self) -> None:
                    self.sent: list[tuple[int, str]] = []

                async def send_message(self, chat_id: int, text: str) -> None:
                    self.sent.append((chat_id, text))

            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            class _Resp:
                def __init__(self, status_code: int, payload: object | None = None, text: str = "") -> None:
                    self.status_code = status_code
                    self._payload = payload
                    self.text = text

                def json(self):
                    return self._payload

            class _FakeClient:
                def __init__(self, *args, **kwargs) -> None:
                    _ = (args, kwargs)

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    _ = (exc_type, exc, tb)
                    return False

                async def get(self, path: str, params=None, headers=None):
                    _ = (params, headers)
                    if path == f"/api/v1/teams/{team_id}/roles":
                        return _Resp(
                            200,
                            payload=[
                                {
                                    "team_role_id": team_role_id,
                                    "role_id": role.role_id,
                                    "working_dir": "/abs/work",
                                    "root_dir": None,
                                    "skills": [{"skill_id": "fs.read_file"}],
                                }
                            ],
                        )
                    return _Resp(404, payload={})

                async def post(self, path: str, json=None, headers=None):
                    raise AssertionError(f"post must not be called when root_dir is missing: {path} {json} {headers}")

            with patch("app.interfaces.telegram_runtime_client.httpx.AsyncClient", _FakeClient, create=True):
                client = ThinRuntimeClient()
                result = await client.execute_run_chain(
                    context=context,
                    team_id=team_id,
                    chat_id=group.group_id,
                    user_id=42,
                    session_token="",
                    roles=[Role(
                        role_id=role.role_id,
                        role_name=role.role_name,
                        description=role.description,
                        base_system_prompt=role.base_system_prompt,
                        extra_instruction=role.extra_instruction,
                        llm_model=role.llm_model,
                        is_active=True,
                    )],
                    user_text="test",
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=10,
                    is_all=False,
                    apply_plugins=True,
                    save_pending_on_unauthorized=True,
                    pending_role_name="dev",
                    allow_orchestrator_post_event=False,
                    chain_origin="group",
                    correlation_id="cid-3",
                )
            self.assertTrue(result.is_ok)
            self.assertTrue(bool(result.value and result.value.pending_saved))
            state = runtime.pending_user_fields.get(42)
            self.assertIsNotNone(state)
            self.assertEqual((state or {}).get("key"), "root_dir")
            self.assertTrue(any(chat_id == 42 for chat_id, _ in bot.sent))


if __name__ == "__main__":
    unittest.main()
