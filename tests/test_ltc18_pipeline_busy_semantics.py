from __future__ import annotations

import asyncio
import sys
import types
import unittest
import json
from time import monotonic
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

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

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

from app.llm_providers import ProviderUserField
from app.llm_router import MissingUserField
from app.pending_user_fields import PendingUserFieldStore
from app.prepost_processing.registry import PrePostProcessingRegistry
from app.role_catalog import RoleCatalog
from app.pending_store import PendingStore
from app.handlers.messages_private import _process_pending_message_for_user
from app.services.role_pipeline import ChainContext, dispatch_mentions, run_chain, send_orchestrator_post_event
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage


class _FakeModel:
    full_id = "provider:model"


class _FakeSessionResolver:
    async def resolve(self, telegram_user_id: int, team_id: int, role, session_token: str, model_override: str | None = None) -> str:
        return "session-1"


class _FakeLLMExecutor:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        team_role_id: int | None = None,
        retries: int = 2,
    ) -> str:
        _ = team_role_id
        if not self._responses:
            raise AssertionError("No fake LLM responses left")
        return self._responses.pop(0)

    def provider_id_for_model(self, model_override: str | None) -> str:
        return "provider"


class _DelayedFakeLLMExecutor(_FakeLLMExecutor):
    def __init__(self, responses: list[str], *, first_delay_sec: float) -> None:
        super().__init__(responses)
        self._first_delay_sec = first_delay_sec
        self._calls = 0

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        team_role_id: int | None = None,
        retries: int = 2,
    ) -> str:
        _ = team_role_id
        self._calls += 1
        if self._calls == 1:
            await asyncio.sleep(self._first_delay_sec)
        return await super().send_with_retries(
            session_id=session_id,
            session_token=session_token,
            content=content,
            role=role,
            model_override=model_override,
            team_role_id=team_role_id,
            retries=retries,
        )


class _MissingFieldThenResponseLLMExecutor(_FakeLLMExecutor):
    def __init__(self, responses: list[str], *, provider_id: str = "provider", field_key: str = "working_dir") -> None:
        super().__init__(responses)
        self._first_call = True
        self._provider_id = provider_id
        self._field_key = field_key

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        team_role_id: int | None = None,
        retries: int = 2,
    ) -> str:
        _ = team_role_id
        if self._first_call:
            self._first_call = False
            raise MissingUserField(
                self._provider_id,
                ProviderUserField(
                    key=self._field_key,
                    prompt="Пришли working_dir",
                    scope="role",
                ),
                int(getattr(role, "role_id", 0)),
            )
        return await super().send_with_retries(
            session_id=session_id,
            session_token=session_token,
            content=content,
            role=role,
            model_override=model_override,
            retries=retries,
        )


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, *, chat_id: int, text: str, **kwargs) -> None:
        self.sent.append(text)


class _NoopPluginManager:
    def apply_postprocess(self, payload: dict, ctx_payload: dict) -> dict:
        return payload


class LTC18PipelineBusySemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadlock_chain_orchestrator_target_roundtrip_completes(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "deadlock_chain.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            group = storage.upsert_group(-7001, "g")
            orchestrator_role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            target_role = storage.upsert_role(
                role_name="target_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, orchestrator_role.role_id)
            storage.ensure_group_role(group.group_id, target_role.role_id)
            storage.set_group_role_mode(group.group_id, orchestrator_role.role_id, "orchestrator")
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            for role_name in ("orchestrator_role", "target_role"):
                (catalog_dir / f"{role_name}.json").write_text(
                    json.dumps(
                        {
                            "role_name": role_name,
                            "description": "d",
                            "base_system_prompt": "sp",
                            "extra_instruction": "ei",
                            "llm_model": None,
                            "is_active": True,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["@target_role do", "target done", "orchestrator ack"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=PendingStore(Path(td) / "deadlock_chain.sqlite3"),
                role_runtime_status_service=status_service,
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=5,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            await asyncio.wait_for(
                send_orchestrator_post_event(
                    context=context,
                    team_id=group.team_id or 0,
                    chat_id=1,
                    user_id=42,
                    reply_to_message_id=10,
                    actor_username="user",
                    session_token="token",
                    orchestrator_role=orchestrator_role,
                    original_user_text="hello",
                    original_reply_text=None,
                    answered_role_name="target_role",
                    role_answer_text="worker answer",
                    chain_context=ChainContext.create(origin="group", reply_to_message_id=10, max_hops=3),
                ),
                timeout=2.0,
            )
            joined = "\n".join(bot.sent)
            self.assertIn("orchestrator ack", joined)
            self.assertIn("target done", joined)

    async def test_pending_replay_processes_message_after_field_value(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "pending_replay.sqlite3"
            storage = Storage(db_path)
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            pending_store = PendingStore(db_path)

            group = storage.upsert_group(-8001, "g")
            role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.set_group_role_mode(group.group_id, role.role_id, "orchestrator")

            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "orchestrator_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "orchestrator_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            pending_store.save(
                telegram_user_id=42,
                chat_id=group.group_id,
                message_id=99,
                role_name="orchestrator_role",
                content="resume this",
                reply_text=None,
                team_id=group.team_id or 0,
            )

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={"provider": SimpleNamespace(auth_mode="none")},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["replayed done", "orchestrator ack"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=pending_store,
                role_runtime_status_service=status_service,
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                cipher=SimpleNamespace(decrypt=lambda token: token),
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            processed = await asyncio.wait_for(_process_pending_message_for_user(42, context), timeout=2.0)
            self.assertTrue(processed)
            self.assertIsNone(pending_store.peek_record(42))
            self.assertIn("replayed done", "\n".join(bot.sent))

    async def test_pending_replay_after_missing_user_field_does_not_wait_free_delay(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "pending_replay_missing_field.sqlite3"
            storage = Storage(db_path)
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=10)
            pending_store = PendingStore(db_path)
            pending_fields = PendingUserFieldStore(db_path)

            group = storage.upsert_group(-8101, "g")
            role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.set_group_role_mode(group.group_id, role.role_id, "orchestrator")
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)

            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "orchestrator_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "orchestrator_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={"provider": SimpleNamespace(auth_mode="none")},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_MissingFieldThenResponseLLMExecutor(["replayed done"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=pending_store,
                pending_user_fields=pending_fields,
                role_runtime_status_service=status_service,
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                cipher=SimpleNamespace(decrypt=lambda token: token),
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            first = await run_chain(
                context=context,
                team_id=team_id,
                chat_id=group.group_id,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="need path",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=100,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=False,
                pending_role_name=role.public_name(),
                allow_orchestrator_post_event=False,
                chain_origin="group",
            )
            self.assertTrue(first.had_error)
            self.assertIsNotNone(pending_store.peek_record(42))
            state = pending_fields.get(42)
            self.assertIsNotNone(state)
            self.assertEqual((state or {}).get("key"), "working_dir")
            status_after_missing = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status_after_missing)
            self.assertEqual(status_after_missing.status if status_after_missing else None, "free")
            self.assertEqual(status_after_missing.last_release_reason if status_after_missing else None, "missing_user_field")

            storage.set_team_role_working_dir_by_id(team_role_id, "/opt/projects/demo")
            started = monotonic()
            processed = await asyncio.wait_for(_process_pending_message_for_user(42, context), timeout=2.0)
            elapsed = monotonic() - started

            self.assertTrue(processed)
            self.assertLess(elapsed, 2.0)
            self.assertIsNone(pending_store.peek_record(42))
            self.assertIn("replayed done", "\n".join(bot.sent))
            team_scoped_value = storage.get_team_role_working_dir_by_id(team_role_id)
            self.assertEqual(team_scoped_value, "/opt/projects/demo")

    async def test_orchestrator_post_event_missing_user_field_releases_immediately(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "post_event_missing_field.sqlite3"
            storage = Storage(db_path)
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=10)
            pending_store = PendingStore(db_path)
            pending_fields = PendingUserFieldStore(db_path)

            group = storage.upsert_group(-8201, "g")
            orchestrator_role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            worker_role = storage.upsert_role(
                role_name="worker_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, orchestrator_role.role_id)
            storage.ensure_group_role(group.group_id, worker_role.role_id)
            storage.set_group_role_mode(group.group_id, orchestrator_role.role_id, "orchestrator")
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, orchestrator_role.role_id, ensure_exists=True) or 0)

            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            for role_name in ("orchestrator_role", "worker_role"):
                (catalog_dir / f"{role_name}.json").write_text(
                    json.dumps(
                        {
                            "role_name": role_name,
                            "description": "d",
                            "base_system_prompt": "sp",
                            "extra_instruction": "ei",
                            "llm_model": None,
                            "is_active": True,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={"provider": SimpleNamespace(auth_mode="none")},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_MissingFieldThenResponseLLMExecutor(["unused"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=pending_store,
                pending_user_fields=pending_fields,
                role_runtime_status_service=status_service,
                role_dispatch_queue_service=None,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            await asyncio.wait_for(
                send_orchestrator_post_event(
                    context=context,
                    team_id=team_id,
                    chat_id=group.group_id,
                    user_id=42,
                    reply_to_message_id=101,
                    actor_username="user",
                    session_token="token",
                    orchestrator_role=orchestrator_role,
                    original_user_text="ask orchestrator",
                    original_reply_text=None,
                    answered_role_name=worker_role.public_name(),
                    role_answer_text="worker answer",
                    chain_context=None,
                ),
                timeout=2.0,
            )
            pending_msg = pending_store.peek_record(42)
            self.assertIsNotNone(pending_msg)
            self.assertEqual(pending_msg["role_name"], orchestrator_role.public_name())
            field_state = pending_fields.get(42)
            self.assertIsNotNone(field_state)
            self.assertEqual((field_state or {}).get("key"), "working_dir")
            status = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status)
            self.assertEqual(status.status if status else None, "free")
            self.assertEqual(status.last_release_reason if status else None, "missing_user_field")

    async def test_dispatch_mentions_queues_same_target_role_fifo(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "dispatch_fifo.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            group = storage.upsert_group(-5001, "g")
            source_role = storage.upsert_role(
                role_name="source_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            target_role = storage.upsert_role(
                role_name="target_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, source_role.role_id)
            storage.ensure_group_role(group.group_id, target_role.role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            for role_name in ("source_role", "target_role"):
                (catalog_dir / f"{role_name}.json").write_text(
                    json.dumps(
                        {
                            "role_name": role_name,
                            "description": "d",
                            "base_system_prompt": "sp",
                            "extra_instruction": "ei",
                            "llm_model": None,
                            "is_active": True,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_DelayedFakeLLMExecutor(["done-1", "done-2"], first_delay_sec=0.35),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=30,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _invoke(chain_id: str):
                return await dispatch_mentions(
                    context=context,
                    team_id=group.team_id or 0,
                    chat_id=1,
                    user_id=42,
                    session_token="token",
                    source_role=source_role,
                    source_response_text="@target_role delegated task",
                    chain_context=ChainContext(
                        chain_id=chain_id,
                        hop=0,
                        max_hops=3,
                        reply_to_message_id=10,
                        origin="group",
                    ),
                )

            with self.assertLogs("bot", level="INFO") as logs:
                t1 = asyncio.create_task(_invoke("c1"))
                await asyncio.sleep(0.05)
                t2 = asyncio.create_task(_invoke("c2"))
                await asyncio.gather(t1, t2)

            joined_sent = "\n".join(bot.sent)
            self.assertIn("done-1", joined_sent)
            self.assertIn("done-2", joined_sent)
            self.assertNotIn("Роль сейчас занята", joined_sent)
            joined_logs = "\n".join(logs.output)
            self.assertIn("role_queue_wait", joined_logs)
            self.assertIn("role_queue_dispatch", joined_logs)

    async def test_send_orchestrator_post_event_queues_fifo(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "orchestrator_post_fifo.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            group = storage.upsert_group(-6001, "g")
            orchestrator_role = storage.upsert_role(
                role_name="orchestrator_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            worker_role = storage.upsert_role(
                role_name="worker_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, orchestrator_role.role_id)
            storage.ensure_group_role(group.group_id, worker_role.role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            for role_name in ("orchestrator_role", "worker_role"):
                (catalog_dir / f"{role_name}.json").write_text(
                    json.dumps(
                        {
                            "role_name": role_name,
                            "description": "d",
                            "base_system_prompt": "sp",
                            "extra_instruction": "ei",
                            "llm_model": None,
                            "is_active": True,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_DelayedFakeLLMExecutor(["post-1", "post-2"], first_delay_sec=0.35),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                plugin_manager=_NoopPluginManager(),
                role_catalog=role_catalog,
                orchestrator_max_chain_auto_steps=30,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _invoke(reply_id: int):
                await send_orchestrator_post_event(
                    context=context,
                    team_id=group.team_id or 0,
                    chat_id=1,
                    user_id=42,
                    reply_to_message_id=reply_id,
                    actor_username="user",
                    session_token="token",
                    orchestrator_role=orchestrator_role,
                    original_user_text="u",
                    original_reply_text=None,
                    answered_role_name="worker_role",
                    role_answer_text="w",
                    chain_context=None,
                )

            with self.assertLogs("bot", level="INFO") as logs:
                t1 = asyncio.create_task(_invoke(20))
                await asyncio.sleep(0.05)
                t2 = asyncio.create_task(_invoke(21))
                await asyncio.gather(t1, t2)

            joined_sent = "\n".join(bot.sent)
            self.assertIn("post-1", joined_sent)
            self.assertIn("post-2", joined_sent)
            self.assertNotIn("Роль сейчас занята", joined_sent)
            joined_logs = "\n".join(logs.output)
            self.assertIn("role_queue_wait", joined_logs)
            self.assertIn("role_queue_dispatch", joined_logs)

    async def test_run_chain_releases_busy_after_response_delivery(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_release.sqlite3")
            status_service = RoleRuntimeStatusService(storage)
            group = storage.upsert_group(-1001, "g")
            role = storage.upsert_role(
                role_name="busy_release_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = int(storage.resolve_team_role_id(group.team_id or 0, role.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(team_role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "busy_release_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "busy_release_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["done"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            result = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="hello",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=10,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            status = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status)
            self.assertEqual(status.status if status else None, "free")
            self.assertEqual(status.last_release_reason if status else None, "response_sent")
            self.assertTrue(any("done" in item for item in bot.sent))

    async def test_run_chain_waits_when_lock_group_blocked_and_then_executes(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_block.sqlite3")
            status_service = RoleRuntimeStatusService(storage)

            group_a = storage.upsert_group(-2001, "a")
            role_a = storage.upsert_role(
                role_name="role_a",
                description="a",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group_a.group_id, role_a.role_id)
            tr_a = int(storage.resolve_team_role_id(group_a.team_id or 0, role_a.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(tr_a)

            group_b = storage.upsert_group(-2002, "b")
            role_b = storage.upsert_role(
                role_name="role_b",
                description="b",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group_b.group_id, role_b.role_id)
            tr_b = int(storage.resolve_team_role_id(group_b.team_id or 0, role_b.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(tr_b)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "role_a.json").write_text(
                json.dumps(
                    {
                        "role_name": "role_a",
                        "description": "a",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (catalog_dir / "role_b.json").write_text(
                json.dumps(
                    {
                        "role_name": "role_b",
                        "description": "b",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            lock_group = storage.create_role_lock_group("shared_pool")
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_a)
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_b)
            status_service.acquire_busy(
                team_role_id=tr_a,
                busy_request_id="req-a",
                busy_owner_user_id=1,
                busy_origin="group",
                preview_text="blocked by A",
                preview_source="user",
            )

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["done-b"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _invoke():
                return await run_chain(
                    context=context,
                    team_id=group_b.team_id or 0,
                    chat_id=1,
                    user_id=42,
                    session_token="token",
                    roles=[role_b],
                    user_text="hello",
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=10,
                    is_all=False,
                    apply_plugins=False,
                    save_pending_on_unauthorized=True,
                )

            task = asyncio.create_task(_invoke())
            await asyncio.sleep(0.2)
            status_service.release_busy(team_role_id=tr_a, release_reason="response_sent")
            result = await task

            self.assertFalse(result.had_error)
            self.assertEqual(result.completed_roles, 1)
            status_b = storage.get_team_role_runtime_status(tr_b)
            self.assertIsNotNone(status_b)
            self.assertEqual(status_b.status if status_b else None, "free")
            status_a = storage.get_team_role_runtime_status(tr_a)
            self.assertEqual(status_a.status if status_a else None, "free")
            joined = "\n".join(bot.sent)
            self.assertIn("done-b", joined)
            self.assertNotIn("Роль сейчас занята", joined)

    async def test_run_chain_honors_free_transition_delay(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_delay.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=1)
            group = storage.upsert_group(-3001, "g")
            role = storage.upsert_role(
                role_name="busy_delay_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = int(storage.resolve_team_role_id(group.team_id or 0, role.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(team_role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "busy_delay_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "busy_delay_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_FakeLLMExecutor(["done-1", "done-2"]),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            first = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="hello",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=10,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )
            self.assertFalse(first.had_error)
            status_after_first = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status_after_first)
            self.assertEqual(status_after_first.status if status_after_first else None, "busy")
            self.assertEqual(status_after_first.free_release_reason_pending if status_after_first else None, "response_sent")

            second = await run_chain(
                context=context,
                team_id=group.team_id or 0,
                chat_id=1,
                user_id=42,
                session_token="token",
                roles=[role],
                user_text="second",
                reply_text=None,
                actor_username="user",
                reply_to_message_id=11,
                is_all=False,
                apply_plugins=False,
                save_pending_on_unauthorized=True,
            )
            self.assertFalse(second.had_error)
            self.assertTrue(any("done-2" in item for item in bot.sent))

    async def test_run_chain_queues_same_role_requests_fifo_with_wait_dispatch_logs(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "busy_queue.sqlite3")
            status_service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
            group = storage.upsert_group(-4001, "g")
            role = storage.upsert_role(
                role_name="busy_queue_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "busy_queue_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "busy_queue_role",
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_catalog = RoleCatalog.load(catalog_dir)
            storage.attach_role_catalog(role_catalog)

            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[_FakeModel()],
                provider_model_map={"provider:model": _FakeModel()},
                llm_executor=_DelayedFakeLLMExecutor(["done-1", "done-2"], first_delay_sec=0.35),
                session_resolver=_FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(SkillRegistry()),
                default_provider_id="provider",
                pending_store=SimpleNamespace(save=lambda *a, **k: None),
                role_runtime_status_service=status_service,
                allow_raw_html=True,
                formatting_mode="html",
                role_catalog=role_catalog,
            )
            bot = _FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            async def _invoke(user_text: str, reply_to_message_id: int):
                return await run_chain(
                    context=context,
                    team_id=group.team_id or 0,
                    chat_id=1,
                    user_id=42,
                    session_token="token",
                    roles=[role],
                    user_text=user_text,
                    reply_text=None,
                    actor_username="user",
                    reply_to_message_id=reply_to_message_id,
                    is_all=False,
                    apply_plugins=False,
                    save_pending_on_unauthorized=True,
                )

            with self.assertLogs("bot", level="INFO") as logs:
                t1 = asyncio.create_task(_invoke("first", 10))
                await asyncio.sleep(0.05)
                t2 = asyncio.create_task(_invoke("second", 11))
                r1, r2 = await asyncio.gather(t1, t2)

            self.assertFalse(r1.had_error)
            self.assertFalse(r2.had_error)
            joined_sent = "\n".join(bot.sent)
            self.assertIn("done-1", joined_sent)
            self.assertIn("done-2", joined_sent)
            self.assertNotIn("Роль сейчас занята", joined_sent)

            joined_logs = "\n".join(logs.output)
            self.assertIn("role_queue_wait", joined_logs)
            self.assertIn("role_queue_dispatch", joined_logs)


if __name__ == "__main__":
    unittest.main()
