from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.use_cases.team_roles import (
    delete_team_role_binding,
    list_team_role_states,
    list_telegram_groups,
    reset_team_role_session,
    set_team_role_enabled,
    set_team_role_mode,
)
from app.storage import Storage


class CoreTeamRolesUseCasesTests(unittest.TestCase):
    def test_list_telegram_groups_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            storage.upsert_group(-1002, "B")
            storage.upsert_group(-1001, "A")

            groups = list_telegram_groups(storage)
            self.assertEqual([g.group_id for g in groups], [-1002, -1001])

    def test_role_state_mutations_and_delete_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1011, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="core_uc_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role.role_id)

            state = list_team_role_states(storage, group.group_id)[0]
            self.assertTrue(state.enabled)

            updated = set_team_role_enabled(storage, group_id=group.group_id, role_id=role.role_id, enabled=False)
            self.assertFalse(updated.enabled)

            updated, _ = set_team_role_mode(storage, group_id=group.group_id, role_id=role.role_id, mode="orchestrator")
            self.assertEqual(updated.mode, "orchestrator")

            deleted_name = delete_team_role_binding(storage, group_id=group.group_id, role_id=role.role_id, user_id=55)
            self.assertEqual(deleted_name, "core_uc_role")
            self.assertFalse(storage.get_team_role(team_id, role.role_id).is_active)

    def test_reset_team_role_session_clears_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1021, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="reset_uc_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)
            storage.save_user_role_session_by_team_role(telegram_user_id=77, team_role_id=team_role_id, session_id="s1")

            runtime = SimpleNamespace(default_provider_id="openai", provider_registry={})
            role_name = reset_team_role_session(runtime, storage, group_id=group.group_id, role_id=role.role_id, user_id=77)

            self.assertEqual(role_name, "reset_uc_role")
            self.assertIsNone(storage.get_user_role_session_by_team_role(77, team_role_id))


if __name__ == "__main__":
    unittest.main()
