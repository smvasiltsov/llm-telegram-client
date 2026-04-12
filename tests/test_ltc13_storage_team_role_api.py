from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC13StorageTeamRoleApiTests(unittest.TestCase):
    def test_team_role_id_first_api_with_compatibility_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(-1005, "g")
            role = storage.upsert_role(
                role_name="dev_team_role_api",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role = storage.ensure_team_role(group.team_id or 0, role.role_id)
            self.assertIsNotNone(team_role.team_role_id)
            team_role_id = int(team_role.team_role_id or 0)

            storage.save_user_role_session_by_team_role(telegram_user_id=7, team_role_id=team_role_id, session_id="sess-tr")
            s1 = storage.get_user_role_session_by_team(7, group.team_id or 0, role.role_id)
            s2 = storage.get_user_role_session_by_team_role(7, team_role_id)
            self.assertIsNotNone(s1)
            self.assertIsNotNone(s2)
            self.assertEqual((s1.team_role_id if s1 else None), team_role_id)
            self.assertEqual((s2.team_role_id if s2 else None), team_role_id)

            storage.upsert_role_prepost_processing_for_team_role(team_role_id, "echo", enabled=True, config={"a": 1})
            p1 = storage.get_role_prepost_processing(group.group_id, role.role_id, "echo")
            p2 = storage.get_role_prepost_processing_for_team_role(team_role_id, "echo")
            self.assertIsNotNone(p1)
            self.assertIsNotNone(p2)
            self.assertEqual((p1.team_role_id if p1 else None), team_role_id)
            self.assertEqual((p2.team_role_id if p2 else None), team_role_id)

            storage.upsert_role_skill_for_team_role(team_role_id, "fs.read_file", enabled=True, config={"root_dir": "/repo"})
            k1 = storage.get_role_skill(group.group_id, role.role_id, "fs.read_file")
            k2 = storage.get_role_skill_for_team_role(team_role_id, "fs.read_file")
            self.assertIsNotNone(k1)
            self.assertIsNotNone(k2)
            self.assertEqual((k1.team_role_id if k1 else None), team_role_id)
            self.assertEqual((k2.team_role_id if k2 else None), team_role_id)

    def test_bind_master_role_to_team_reactivates_after_detach(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(-1015, "g")
            role = storage.upsert_role(
                role_name="dev_rebind_api",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_id = group.team_id or 0
            team_role, created = storage.bind_master_role_to_team(team_id, role.role_id)
            self.assertTrue(created)
            self.assertTrue(team_role.is_active)

            storage.deactivate_team_role(team_id, role.role_id)
            detached = storage.get_team_role(team_id, role.role_id)
            self.assertFalse(detached.is_active)

            rebound, created_again = storage.bind_master_role_to_team(team_id, role.role_id)
            self.assertTrue(created_again)
            self.assertTrue(rebound.is_active)
            self.assertTrue(rebound.enabled)

    def test_provider_role_scoped_values_are_team_role_scoped_with_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            g1 = storage.upsert_group(-1115, "g1")
            g2 = storage.upsert_group(-1116, "g2")
            role = storage.upsert_role(
                role_name="dev_team_role_scope_api",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            tr1 = storage.ensure_team_role(g1.team_id or 0, role.role_id)
            tr2 = storage.ensure_team_role(g2.team_id or 0, role.role_id)
            self.assertIsNotNone(tr1.team_role_id)
            self.assertIsNotNone(tr2.team_role_id)
            tr1_id = int(tr1.team_role_id or 0)
            tr2_id = int(tr2.team_role_id or 0)

            storage.set_provider_user_value_by_team_role("provider", "working_dir", tr1_id, "/team1")
            self.assertEqual(
                storage.get_provider_user_value_by_team_role("provider", "working_dir", tr1_id),
                "/team1",
            )
            self.assertIsNone(
                storage.get_provider_user_value_by_team_role("provider", "working_dir", tr2_id),
            )

            storage.set_provider_user_value("provider", "working_dir", role.role_id, "/legacy")
            self.assertEqual(
                storage.get_provider_user_value_by_team_role_or_role(
                    "provider",
                    "working_dir",
                    team_role_id=tr2_id,
                    role_id=role.role_id,
                ),
                "/legacy",
            )

    def test_team_role_paths_are_stored_on_team_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(-1120, "g")
            role = storage.upsert_role(
                role_name="dev_team_role_paths",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_id = int(group.team_id or 0)
            team_role = storage.ensure_team_role(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)

            with storage.transaction(immediate=True):
                storage.set_team_role_working_dir(team_id, role.role_id, "/abs/work")
                storage.set_team_role_root_dir_by_id(team_role_id, "/abs/root")

            updated = storage.get_team_role(team_id, role.role_id)
            self.assertEqual(updated.working_dir, "/abs/work")
            self.assertEqual(updated.root_dir, "/abs/root")
            self.assertEqual(storage.get_team_role_working_dir_by_id(team_role_id), "/abs/work")
            self.assertEqual(storage.get_team_role_root_dir(team_id, role.role_id), "/abs/root")


if __name__ == "__main__":
    unittest.main()
