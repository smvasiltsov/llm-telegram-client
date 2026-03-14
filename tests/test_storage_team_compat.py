from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.storage import Storage


class StorageTeamCompatibilityTests(unittest.TestCase):
    def test_group_wrappers_work_via_team_layer(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-7001, "Team A")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )

            gr = storage.ensure_group_role(group.group_id, role.role_id)
            self.assertEqual(gr.role_id, role.role_id)

            storage.set_group_role_display_name(group.group_id, role.role_id, "developer")
            storage.set_group_role_prompt(group.group_id, role.role_id, "team prompt")
            storage.set_group_role_mode(group.group_id, role.role_id, "orchestrator")

            team_id = storage.resolve_team_id_by_group_id_legacy(group.group_id)
            team = storage.get_team(team_id)
            self.assertTrue(team.public_id.startswith("team-tg-"))

            binding = storage.get_team_binding(interface_type="telegram", external_id=str(group.group_id))
            self.assertEqual(binding.team_id, team_id)

            team_role = storage.get_team_role(team_id, role.role_id)
            self.assertEqual(team_role.display_name, "developer")
            self.assertEqual(team_role.system_prompt_override, "team prompt")
            self.assertEqual(team_role.mode, "orchestrator")

            roles = storage.list_roles_for_group(group.group_id)
            self.assertEqual(len(roles), 1)
            self.assertEqual(roles[0].public_name(), "developer")
            self.assertTrue(storage.group_role_name_exists(group.group_id, "developer"))


if __name__ == "__main__":
    unittest.main()
