from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import dataclass
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

from app.prepost_processing.registry import PrePostProcessingRegistry
from app.llm_providers import ProviderConfig, ProviderUserField
from app.services.role_pipeline import execute_role_request
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage import Storage
from skills.fs_list_dir.skill import FSListDirSkill
from skills_sdk.contract import SkillResult, SkillSpec


class EchoSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="echo.skill",
            name="Echo Skill",
            version="0.1.0",
            description="Echoes provided arguments.",
            input_schema={"type": "object"},
        )

    def validate_config(self, config: dict) -> list[str]:
        if config.get("invalid"):
            return ["invalid config"]
        return []

    def run(self, ctx, arguments: dict, config: dict) -> SkillResult:
        return SkillResult(ok=True, output={"echo": arguments.get("text")})


@dataclass
class FakeModel:
    full_id: str


class FakeSessionResolver:
    async def resolve(self, telegram_user_id: int, group_id: int, role, session_token: str, model_override: str | None = None) -> str:
        return "session-1"


class FakeLLMExecutor:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.contents: list[str] = []

    async def send_with_retries(
        self,
        session_id: str,
        session_token: str,
        content: str,
        role,
        model_override: str | None = None,
        retries: int = 2,
    ) -> str:
        self.contents.append(content)
        if not self._responses:
            raise AssertionError("No fake LLM responses left")
        return self._responses.pop(0)


class RolePipelineSkillsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_role_request_uses_skill_loop_when_skills_enabled(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1001, "g")
            role = storage.upsert_role(
                role_name="skill_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "echo.skill", enabled=True, config={})

            skills_registry = SkillRegistry()
            skills_registry.register(EchoSkill())
            executor = FakeLLMExecutor(
                [
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "echo.skill", "arguments": {"text": "hello"}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done"}}),
                ]
            )
            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(skills_registry),
                default_provider_id="provider",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))

            result = await execute_role_request(
                context=context,
                chat_id=group.group_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role"],
                recipient="skill_role",
            )

            self.assertEqual(result.response_text, "done")
            self.assertEqual(result.model_override, "provider:model")
            self.assertEqual(len(executor.contents), 2)
            self.assertIn('"skills"', executor.contents[0])
            logged = storage.get_skill_run(1)
            self.assertIsNotNone(logged)
            assert logged is not None
            self.assertEqual(logged.skill_id, "echo.skill")
            self.assertEqual(logged.status, "ok")

    async def test_execute_role_request_parse_fallback_returns_raw_text(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1002, "g")
            role = storage.upsert_role(
                role_name="skill_role_fallback",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "echo.skill", enabled=True, config={})

            skills_registry = SkillRegistry()
            skills_registry.register(EchoSkill())
            executor = FakeLLMExecutor(["plain text answer"])
            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(skills_registry),
                default_provider_id="provider",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))

            result = await execute_role_request(
                context=context,
                chat_id=group.group_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_fallback"],
                recipient="skill_role_fallback",
            )

            self.assertEqual(result.response_text, "plain text answer")
            self.assertIsNone(storage.get_skill_run(1))

    async def test_execute_role_request_logs_invalid_skill_config(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1003, "g")
            role = storage.upsert_role(
                role_name="skill_role_invalid",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "echo.skill", enabled=True, config={"invalid": True})

            skills_registry = SkillRegistry()
            skills_registry.register(EchoSkill())
            executor = FakeLLMExecutor(
                [
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "echo.skill", "arguments": {"text": "hello"}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done after invalid config"}}),
                ]
            )
            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={},
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(skills_registry),
                default_provider_id="provider",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))

            result = await execute_role_request(
                context=context,
                chat_id=group.group_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_invalid"],
                recipient="skill_role_invalid",
            )

            self.assertEqual(result.response_text, "done after invalid config")
            logged = storage.get_skill_run(1)
            self.assertIsNotNone(logged)
            assert logged is not None
            self.assertEqual(logged.status, "invalid_config")
            self.assertFalse(logged.ok)

    async def test_execute_role_request_uses_provider_working_dir_for_fs_skill(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "alpha.txt").write_text("hello", encoding="utf-8")
            storage = Storage(root / "test.sqlite3")
            group = storage.upsert_group(-1004, "g")
            role = storage.upsert_role(
                role_name="skill_role_fs",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "fs.list_dir", enabled=True, config={})
            storage.set_provider_user_value("provider", "working_dir", role.role_id, str(root))

            skills_registry = SkillRegistry()
            skills_registry.register(FSListDirSkill())
            executor = FakeLLMExecutor(
                [
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "fs.list_dir", "arguments": {"path": "."}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done"}}),
                ]
            )
            provider = ProviderConfig(
                provider_id="provider",
                label="Provider",
                base_url="http://example.invalid",
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
                        prompt="wd",
                        scope="role",
                    )
                },
            )
            runtime = SimpleNamespace(
                storage=storage,
                provider_registry={"provider": provider},
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                prepost_processing_registry=PrePostProcessingRegistry(),
                skills_service=SkillService(skills_registry),
                default_provider_id="provider",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))

            result = await execute_role_request(
                context=context,
                chat_id=group.group_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="list files",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_fs"],
                recipient="skill_role_fs",
            )

            self.assertEqual(result.response_text, "done")
            logged = storage.get_skill_run(1)
            self.assertIsNotNone(logged)
            assert logged is not None
            self.assertEqual(logged.skill_id, "fs.list_dir")
            self.assertEqual(logged.status, "ok")


if __name__ == "__main__":
    unittest.main()
