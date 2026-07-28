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

    def test_generic_binding_helpers_match_telegram_wrappers(self) -> None:
        with TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            with storage.transaction(immediate=True):
                team_id = storage.upsert_team_binding_for_interface(
                    interface_type="telegram",
                    external_id=-8002,
                    external_title="Team B",
                    is_active=True,
                )
            self.assertEqual(storage.resolve_team_id_by_binding(interface_type="telegram", external_id=-8002), team_id)
            self.assertEqual(storage.resolve_team_id_by_telegram_chat(-8002), team_id)
            self.assertEqual(storage.resolve_binding_external_id_by_team(team_id=team_id, interface_type="telegram"), "-8002")

            with storage.transaction(immediate=True):
                storage.set_team_binding_active(interface_type="telegram", external_id=-8002, is_active=False)
            binding = storage.get_team_binding(interface_type="telegram", external_id="-8002")
            self.assertFalse(binding.is_active)


if __name__ == "__main__":
    unittest.main()
