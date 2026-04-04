from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

if "telegram" not in sys.modules:
    telegram_module = types.ModuleType("telegram")
    telegram_constants = types.ModuleType("telegram.constants")
    telegram_error = types.ModuleType("telegram.error")
    telegram_ext = types.ModuleType("telegram.ext")

    class _ParseMode:
        HTML = "HTML"
        MARKDOWN = "MARKDOWN"

    class _BadRequest(Exception):
        pass

    class _Dummy:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class _ContextTypes:
        DEFAULT_TYPE = object

    telegram_constants.ParseMode = _ParseMode
    telegram_error.BadRequest = _BadRequest
    telegram_ext.ContextTypes = _ContextTypes
    telegram_module.constants = telegram_constants
    telegram_module.error = telegram_error
    telegram_module.ext = telegram_ext
    telegram_module.InlineKeyboardButton = _Dummy
    telegram_module.InlineKeyboardMarkup = _Dummy
    telegram_module.Update = _Dummy
    telegram_module.WebAppInfo = _Dummy

    sys.modules["telegram"] = telegram_module
    sys.modules["telegram.constants"] = telegram_constants
    sys.modules["telegram.error"] = telegram_error
    sys.modules["telegram.ext"] = telegram_ext

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")
    httpx_module.HTTPStatusError = Exception
    sys.modules["httpx"] = httpx_module

from app.llm_router import LLMRouter
from app.pending_store import PendingStore
from app.prepost_processing.registry import PrePostProcessingRegistry
from app.role_catalog import RoleCatalog
from app.services.role_pipeline import run_chain
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.session_resolver import SessionResolver
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage


class _FakeModel:
    full_id = "provider:model"


class _LocalOnlyRouter:
    def supports(self, model_override: str | None, capability: str) -> bool:
        return capability != "create_session"

    async def create_session(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("create_session should not be called")

    async def rename_session(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("rename_session should not be called")

    async def send_message(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("send_message should not be called")


class _ProxyLLMExecutor:
    def __init__(self, router: LLMRouter, role_model: str | None = "fake_provider:model-1") -> None:
        self._router = router
        self._role_model = role_model

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        retries: int = 2,
    ) -> str:
        return await self._router.send_message(
            session_id=session_id,
            session_token=session_token,
            content=content,
            model_override=model_override or self._role_model,
            role_id=role.role_id,
        )

    def provider_id_for_model(self, model_override: str | None) -> str:
        return self._router.provider_id_for_model(model_override or self._role_model)


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, *, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append(text)


class _NoopPluginManager:
    def apply_postprocess(self, payload: dict, ctx_payload: dict) -> dict:
        return payload


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, headers=None, json=None):  # noqa: A002
        self.calls.append((method, path))
        if path.endswith("/message"):
            return _FakeResponse({"reply": "ok from worker"})
        if path == "/sessions":
            return _FakeResponse({"session_id": "remote-session"})
        return _FakeResponse({"ok": True})


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.is_error = False
        self.headers = {}
        self.encoding = "utf-8"
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None

    async def aread(self):
        return b""


class _ProviderCfg:
    def __init__(self) -> None:
        self.provider_id = "fake_provider"
        self.adapter = "generic"
        self.capabilities = {
            "list_sessions": False,
            "create_session": False,
            "rename_session": False,
            "model_select": True,
        }
        self.user_fields = {}
        self.history_enabled = False
        self.history_limit = 20
        self.auth_mode = "none"
        self.endpoints = {
            "send_message": {
                "path": "/sessions/{session_id}/message",
                "method": "POST",
                "request": {"body_template": {"message": "{{content}}"}},
                "response": {"content_path": "reply"},
            }
        }


class LTC64LLMHistoryUowGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_conversation_message_runs_inside_transaction(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc64_guard.sqlite3")
            with storage.transaction(immediate=True):
                storage.add_conversation_message("s1", "user", "seed")
            router = LLMRouter(
                provider_registry={"fake_provider": _ProviderCfg()},  # type: ignore[arg-type]
                clients={"fake_provider": _FakeClient()},  # type: ignore[arg-type]
                storage=storage,
                default_provider_id="fake_provider",
            )
            storage.enable_write_uow_guard()
            observed_tx_depths: list[int] = []
            original_add = storage.add_conversation_message

            def _wrapped_add(*args, **kwargs):
                observed_tx_depths.append(storage._tx_depth)
                return original_add(*args, **kwargs)

            with patch.object(storage, "add_conversation_message", side_effect=_wrapped_add):
                reply = await router.send_message(
                    session_id="s1",
                    session_token="token",
                    content="hello",
                    model_override="fake_provider:model-1",
                    role_id=1,
                )

            self.assertEqual(reply, "ok from worker")
            self.assertGreaterEqual(len(observed_tx_depths), 2)
            self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    async def test_group_mention_succeeds_with_history_write_guard_enabled(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "ltc64_group.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9501, "grp")
                role = storage.upsert_role(
                    role_name="worker",
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model="fake_provider:model-1",
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)

            role_catalog_dir = Path(td) / "roles_catalog"
            role_catalog_dir.mkdir(parents=True, exist_ok=True)
            (role_catalog_dir / "worker.json").write_text(
                '{"role_name":"worker","description":"d","base_system_prompt":"sp","extra_instruction":"ei","llm_model":"fake_provider:model-1","is_active":true}',
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(role_catalog_dir)
            storage.attach_role_catalog(role_catalog)
            storage.enable_write_uow_guard()

            llm_router = LLMRouter(
                provider_registry={"fake_provider": _ProviderCfg()},  # type: ignore[arg-type]
                clients={"fake_provider": _FakeClient()},  # type: ignore[arg-type]
                storage=storage,
                default_provider_id="fake_provider",
            )

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={"fake_provider": _ProviderCfg()},
                provider_models=[_FakeModel()],
                provider_model_map={"fake_provider:model-1": _FakeModel()},
                llm_executor=_ProxyLLMExecutor(llm_router),
                session_resolver=SessionResolver(storage, _LocalOnlyRouter()),  # type: ignore[arg-type]
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="fake_provider",
                pending_store=PendingStore(db_path),
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=3,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            result = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=group.group_id,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="@worker ping",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=11,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=False,
            )

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            self.assertIn("ok from worker", "\n".join(bot.sent))


if __name__ == "__main__":
    unittest.main()
