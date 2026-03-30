from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, *args, response=None, **kwargs) -> None:
            super().__init__(*args)
            self.response = response

    httpx_module.HTTPStatusError = _HTTPStatusError
    sys.modules["httpx"] = httpx_module

from app.llm_providers import ProviderConfig, ProviderUserField
from app.llm_router import MissingUserField
from app.services.skill_calling_loop import SkillCallingLoop
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
        return []

    def run(self, ctx, arguments: dict, config: dict) -> SkillResult:
        return SkillResult(ok=True, output={"echo": arguments.get("text")})


@dataclass
class FakeModel:
    full_id: str


class FakeSessionResolver:
    async def resolve(self, telegram_user_id: int, team_id: int, role, session_token: str, model_override: str | None = None) -> str:
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


class SkillCallingLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_executes_skill_and_returns_final_answer(self) -> None:
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

            registry = SkillRegistry()
            registry.register(EchoSkill())
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {
                                "skill_id": "echo.skill",
                                "arguments": {"text": "hello"},
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "final_answer",
                            "answer": {"text": "done"},
                        }
                    ),
                ]
            )
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
            )

            result = await loop.run(
                team_id=group.team_id,
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

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(result.final_answer_text, "done")
            self.assertEqual(len(result.executed_skills), 1)
            self.assertEqual(result.executed_skills[0].skill_id, "echo.skill")
            self.assertEqual(result.executed_skills[0].output, {"echo": "hello"})
            self.assertEqual(len(executor.contents), 2)
            self.assertIn('"skills"', executor.contents[0])
            self.assertIn('"history": [{"skill_id": "echo.skill"', executor.contents[1])

    async def test_loop_uses_compact_followup_mode_after_skill(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1010, "g")
            role = storage.upsert_role(
                role_name="skill_role_compact",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "echo.skill", enabled=True, config={})

            registry = SkillRegistry()
            registry.register(EchoSkill())
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {
                                "skill_id": "echo.skill",
                                "arguments": {"text": "hello"},
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "final_answer",
                            "answer": {"text": "done"},
                        }
                    ),
                ]
            )
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
                followup_mode="compact",
            )

            result = await loop.run(
                team_id=group.team_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_compact"],
                recipient="skill_role_compact",
            )

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(len(executor.contents), 2)
            self.assertTrue(executor.contents[0].startswith("INPUT_JSON:\n"))
            self.assertTrue(executor.contents[1].startswith("SKILL_RESULT:\n"))
            self.assertIn('"skill_id": "echo.skill"', executor.contents[1])

    async def test_loop_stops_on_repeated_same_skill_call(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1002, "g")
            role = storage.upsert_role(
                role_name="skill_role_repeat",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)

            registry = SkillRegistry()
            service = SkillService(registry)
            repeated_call = json.dumps(
                {
                    "type": "skill_call",
                    "skill_call": {
                        "skill_id": "missing.skill",
                        "arguments": {"text": "loop"},
                    },
                }
            )
            executor = FakeLLMExecutor(responses=[repeated_call, repeated_call, repeated_call, repeated_call])
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
            )

            result = await loop.run(
                team_id=group.team_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="loop",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_repeat"],
                recipient="skill_role_repeat",
                max_steps=6,
            )

            self.assertEqual(result.status, "guard_repeated_call")
            self.assertEqual(len(result.executed_skills), 3)
            self.assertTrue(all(item.status == "not_enabled" for item in result.executed_skills))

    async def test_loop_uses_provider_working_dir_for_filesystem_skills(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "alpha.txt").write_text("hello", encoding="utf-8")
            storage = Storage(root / "test.sqlite3")
            group = storage.upsert_group(-1003, "g")
            role = storage.upsert_role(
                role_name="fs_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "fs.list_dir", enabled=True, config={})
            storage.set_provider_user_value("provider", "working_dir", role.role_id, str(root))

            registry = SkillRegistry()
            registry.register(FSListDirSkill())
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
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
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={"provider": provider},
            )

            result = await loop.run(
                team_id=group.team_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="list files",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["fs_role"],
                recipient="fs_role",
            )

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(result.executed_skills[0].status, "ok")
            self.assertEqual(result.executed_skills[0].skill_id, "fs.list_dir")
            entries = result.executed_skills[0].output["entries"]
            self.assertTrue(any(item["name"] == "alpha.txt" for item in entries))

    async def test_loop_requests_root_dir_when_filesystem_skill_has_no_path_source(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1004, "g")
            role = storage.upsert_role(
                role_name="fs_role_missing",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "fs.list_dir", enabled=True, config={})

            registry = SkillRegistry()
            registry.register(FSListDirSkill())
            service = SkillService(registry)
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=FakeLLMExecutor([]),
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
            )

            with self.assertRaises(MissingUserField) as ctx:
                await loop.run(
                    team_id=group.team_id,
                    user_id=42,
                    role=role,
                    session_token="token",
                    user_text="list files",
                    reply_text=None,
                    actor_username="user",
                    trigger_type="mention_role",
                    mentioned_roles=["fs_role_missing"],
                    recipient="fs_role_missing",
                )

            self.assertEqual(ctx.exception.provider_id, "skills")
            self.assertEqual(ctx.exception.field.key, "root_dir")

    async def test_loop_uses_team_scoped_skills_root_dir_without_reasking(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "alpha.txt").write_text("hello", encoding="utf-8")
            storage = Storage(root / "test.sqlite3")
            group = storage.upsert_group(-1005, "g")
            role = storage.upsert_role(
                role_name="fs_role_team_scope_root",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "fs.list_dir", enabled=True, config={})
            team_role_id = storage.resolve_team_role_id(int(group.team_id or 0), role.role_id, ensure_exists=True)
            self.assertIsNotNone(team_role_id)
            storage.set_provider_user_value_by_team_role("skills", "root_dir", int(team_role_id or 0), str(root))

            registry = SkillRegistry()
            registry.register(FSListDirSkill())
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "fs.list_dir", "arguments": {"path": "."}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done"}}),
                ]
            )
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
            )

            result = await loop.run(
                team_id=int(group.team_id or 0),
                user_id=42,
                role=role,
                session_token="token",
                user_text="list files",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["fs_role_team_scope_root"],
                recipient="fs_role_team_scope_root",
            )

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(result.executed_skills[0].status, "ok")
            self.assertEqual(result.executed_skills[0].skill_id, "fs.list_dir")

    async def test_skills_to_llm_delay_applies_after_executed_skill_step(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1101, "g")
            role = storage.upsert_role(
                role_name="skill_role_delay",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.upsert_role_skill(group.group_id, role.role_id, "echo.skill", enabled=True, config={})

            registry = SkillRegistry()
            registry.register(EchoSkill())
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "echo.skill", "arguments": {"text": "hello"}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done"}}),
                ]
            )
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
                skills_to_llm_delay_sec=2,
            )

            sleep_calls: list[float] = []

            async def _fake_sleep(value: float) -> None:
                sleep_calls.append(float(value))

            loop._sleep_for_skills_to_llm_delay = _fake_sleep  # type: ignore[method-assign]
            result = await loop.run(
                team_id=group.team_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_delay"],
                recipient="skill_role_delay",
            )

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(sleep_calls, [2.0])

    async def test_skills_to_llm_delay_not_applied_without_executed_skill(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1102, "g")
            role = storage.upsert_role(
                role_name="skill_role_no_delay",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)

            registry = SkillRegistry()
            service = SkillService(registry)
            executor = FakeLLMExecutor(
                responses=[
                    json.dumps(
                        {
                            "type": "skill_call",
                            "skill_call": {"skill_id": "missing.skill", "arguments": {"text": "loop"}},
                        }
                    ),
                    json.dumps({"type": "final_answer", "answer": {"text": "done"}}),
                ]
            )
            loop = SkillCallingLoop(
                storage=storage,
                llm_executor=executor,
                session_resolver=FakeSessionResolver(),
                skills_service=service,
                provider_models=[FakeModel(full_id="provider:model")],
                provider_model_map={"provider:model": FakeModel(full_id="provider:model")},
                provider_registry={},
                skills_to_llm_delay_sec=3,
            )

            sleep_calls: list[float] = []

            async def _fake_sleep(value: float) -> None:
                sleep_calls.append(float(value))

            loop._sleep_for_skills_to_llm_delay = _fake_sleep  # type: ignore[method-assign]
            result = await loop.run(
                team_id=group.team_id,
                user_id=42,
                role=role,
                session_token="token",
                user_text="say hello",
                reply_text=None,
                actor_username="user",
                trigger_type="mention_role",
                mentioned_roles=["skill_role_no_delay"],
                recipient="skill_role_no_delay",
            )

            self.assertEqual(result.status, "final_answer")
            self.assertEqual(sleep_calls, [])
