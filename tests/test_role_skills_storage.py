from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class StorageRoleSkillsTests(unittest.TestCase):
    def test_role_skills_crud_and_logging(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(100, "Test Group")
            role = storage.upsert_role(
                role_name="skill_role",
                description="Role for skills",
                base_system_prompt="system",
                extra_instruction="extra",
                llm_model=None,
                is_active=True,
            )

            role_skill = storage.upsert_role_skill(
                group.group_id,
                role.role_id,
                "fs.read_file",
                enabled=True,
                config={"root_dir": "/repo"},
            )
            self.assertEqual(role_skill.skill_id, "fs.read_file")
            self.assertTrue(role_skill.enabled)

            listed_all = storage.list_role_skills(group.group_id, role.role_id)
            self.assertEqual([item.skill_id for item in listed_all], ["fs.read_file"])

            storage.set_role_skill_enabled(group.group_id, role.role_id, "fs.read_file", False)
            listed_enabled = storage.list_role_skills(group.group_id, role.role_id, enabled_only=True)
            self.assertEqual(listed_enabled, [])

            storage.set_role_skill_config(group.group_id, role.role_id, "fs.read_file", {"root_dir": "/srv/app"})
            fetched = storage.get_role_skill(group.group_id, role.role_id, "fs.read_file")
            assert fetched is not None
            self.assertEqual(json.loads(fetched.config_json or "{}"), {"root_dir": "/srv/app"})

            skill_run = storage.log_skill_run(
                chain_id="chain-1",
                step_index=2,
                telegram_user_id=42,
                chat_id=group.group_id,
                role_id=role.role_id,
                skill_id="fs.read_file",
                arguments={"path": "README.md"},
                config={"root_dir": "/srv/app"},
                status="ok",
                ok=True,
                duration_ms=123,
                output={"path": "README.md", "content": "hello"},
            )
            self.assertEqual(skill_run.skill_id, "fs.read_file")
            self.assertTrue(skill_run.ok)
            self.assertEqual(json.loads(skill_run.arguments_json or "{}"), {"path": "README.md"})

            storage.delete_role_skill(group.group_id, role.role_id, "fs.read_file")
            self.assertIsNone(storage.get_role_skill(group.group_id, role.role_id, "fs.read_file"))


if __name__ == "__main__":
    unittest.main()
