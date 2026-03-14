from __future__ import annotations

import sys
import types
import unittest
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

from app.session_resolver import SessionResolver
from app.storage import Storage


class _NoSessionLLMRouter:
    def supports(self, model_override: str | None, capability: str) -> bool:
        return False


class LTC13InheritanceOverrideTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_warmup_uses_master_then_team_overrides(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1011, "g")
            role = storage.upsert_role(
                role_name="ltc13_inherit",
                description="d",
                base_system_prompt="master prompt",
                extra_instruction="master extra",
                llm_model=None,
                is_active=True,
            )
            team_role = storage.ensure_team_role(group.team_id or 0, role.role_id)
            resolver = SessionResolver(storage, _NoSessionLLMRouter())

            session_id_1 = await resolver.ensure_session(
                telegram_user_id=77,
                team_id=group.team_id or 0,
                role=role,
                session_token="token",
                model_override=None,
            )
            messages_1 = storage.list_conversation_messages(session_id_1)
            self.assertEqual(len(messages_1), 1)
            self.assertIn("master prompt", messages_1[0][1])
            self.assertIn("master extra", messages_1[0][1])

            if team_role.team_role_id is None:
                self.fail("team_role_id is required for LTC-13 flow")
            storage.delete_user_role_session_by_team_role(77, int(team_role.team_role_id))
            storage.set_team_role_prompt(group.team_id or 0, role.role_id, "team prompt")
            storage.set_team_role_extra_instruction(group.team_id or 0, role.role_id, "team extra")

            session_id_2 = await resolver.ensure_session(
                telegram_user_id=77,
                team_id=group.team_id or 0,
                role=role,
                session_token="token",
                model_override=None,
            )
            messages_2 = storage.list_conversation_messages(session_id_2)
            self.assertEqual(len(messages_2), 1)
            self.assertIn("team prompt", messages_2[0][1])
            self.assertIn("team extra", messages_2[0][1])
            self.assertNotIn("master extra", messages_2[0][1])

    def test_clone_reuses_master_role_and_copies_processing_bindings(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            src = storage.upsert_group(-1012, "src")
            dst = storage.upsert_group(-1013, "dst")
            master_role = storage.upsert_role(
                role_name="ltc13_master_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            src_team_id = src.team_id or 0
            dst_team_id = dst.team_id or 0
            src_team_role = storage.ensure_team_role(src_team_id, master_role.role_id)
            storage.set_team_role_prompt(src_team_id, master_role.role_id, "src prompt")
            storage.set_team_role_extra_instruction(src_team_id, master_role.role_id, "src extra")
            storage.set_team_role_model(src_team_id, master_role.role_id, "provider:model-a")
            storage.set_team_role_user_prompt_suffix(src_team_id, master_role.role_id, "src suffix")
            storage.set_team_role_user_reply_prefix(src_team_id, master_role.role_id, "src prefix")
            storage.upsert_role_skill_for_team(src_team_id, master_role.role_id, "echo.skill", enabled=True, config={"x": 1})
            storage.upsert_role_prepost_processing_for_team(
                src_team_id,
                master_role.role_id,
                "echo",
                enabled=True,
                config={"y": 2},
            )
            src_team_role = storage.get_team_role(src_team_id, master_role.role_id)

            # Simulate clone behavior in handlers: bind same master role to target team.
            storage.ensure_team_role(dst_team_id, master_role.role_id)
            dst_team_role = storage.get_team_role(dst_team_id, master_role.role_id)
            storage.set_team_role_display_name(dst_team_id, master_role.role_id, "copied")
            storage.set_team_role_prompt(dst_team_id, master_role.role_id, src_team_role.system_prompt_override)
            storage.set_team_role_extra_instruction(dst_team_id, master_role.role_id, src_team_role.extra_instruction_override)
            storage.set_team_role_model(dst_team_id, master_role.role_id, src_team_role.model_override)
            storage.set_team_role_user_prompt_suffix(dst_team_id, master_role.role_id, src_team_role.user_prompt_suffix)
            storage.set_team_role_user_reply_prefix(dst_team_id, master_role.role_id, src_team_role.user_reply_prefix)
            if src_team_role.team_role_id is None or dst_team_role.team_role_id is None:
                self.fail("team_role_id required for clone flow")
            storage.clone_team_role_processing_bindings(int(src_team_role.team_role_id), int(dst_team_role.team_role_id))

            all_roles = storage.list_active_roles()
            self.assertEqual(len(all_roles), 1, "clone must not create a second master role")

            copied = storage.get_team_role(dst_team_id, master_role.role_id)
            self.assertEqual(copied.system_prompt_override, "src prompt")
            self.assertEqual(copied.extra_instruction_override, "src extra")
            self.assertEqual(copied.model_override, "provider:model-a")
            self.assertEqual(copied.user_prompt_suffix, "src suffix")
            self.assertEqual(copied.user_reply_prefix, "src prefix")

            copied_skills = storage.list_role_skills_for_team(dst_team_id, master_role.role_id, enabled_only=False)
            self.assertEqual([s.skill_id for s in copied_skills], ["echo.skill"])
            copied_prepost = storage.list_role_prepost_processing_for_team(dst_team_id, master_role.role_id, enabled_only=False)
            self.assertEqual([p.prepost_processing_id for p in copied_prepost], ["echo"])


if __name__ == "__main__":
    unittest.main()
