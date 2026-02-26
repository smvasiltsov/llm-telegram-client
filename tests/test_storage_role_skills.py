from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class StorageRoleSkillsTests(unittest.TestCase):
    def test_role_skills_crud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(-1001, "g")
            role = storage.upsert_role(
                role_name="dev_test",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)

            rs = storage.upsert_role_skill(
                group.group_id,
                role.role_id,
                "echo",
                enabled=True,
                config={"a": 1},
            )
            self.assertEqual(rs.skill_id, "echo")
            self.assertTrue(rs.enabled)
            self.assertEqual(json.loads(rs.config_json or "{}"), {"a": 1})

            listed_all = storage.list_role_skills(group.group_id, role.role_id)
            self.assertEqual([x.skill_id for x in listed_all], ["echo"])

            storage.set_role_skill_enabled(group.group_id, role.role_id, "echo", False)
            listed_enabled = storage.list_role_skills(group.group_id, role.role_id, enabled_only=True)
            self.assertEqual(listed_enabled, [])

            storage.set_role_skill_config(group.group_id, role.role_id, "echo", {"b": 2})
            got = storage.get_role_skill(group.group_id, role.role_id, "echo")
            self.assertIsNotNone(got)
            assert got is not None
            self.assertEqual(json.loads(got.config_json or "{}"), {"b": 2})

            storage.delete_role_skill(group.group_id, role.role_id, "echo")
            self.assertIsNone(storage.get_role_skill(group.group_id, role.role_id, "echo"))


if __name__ == "__main__":
    unittest.main()
