from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.role_catalog import RoleCatalog
from app.storage import Storage


class LTC12RuntimeJsonSwitchTests(unittest.TestCase):
    def test_storage_reads_master_fields_from_role_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)

            group = storage.upsert_group(-100222, "team")
            role = storage.upsert_role(
                role_name="json_master",
                description="db desc",
                base_system_prompt="db prompt",
                extra_instruction="db extra",
                llm_model="db:model",
                is_active=True,
            )
            storage.ensure_team_role(group.team_id or 0, role.role_id)

            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "json_master.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role_name": "json_master",
                        "description": "catalog desc",
                        "base_system_prompt": "catalog prompt",
                        "extra_instruction": "catalog extra",
                        "llm_model": "catalog:model",
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            storage.attach_role_catalog(RoleCatalog.load(root))

            from_name = storage.get_role_by_name("json_master")
            self.assertEqual(from_name.description, "catalog desc")
            self.assertEqual(from_name.base_system_prompt, "catalog prompt")
            self.assertEqual(from_name.extra_instruction, "catalog extra")
            self.assertEqual(from_name.llm_model, "catalog:model")

            from_team = storage.list_roles_for_group(group.group_id)
            self.assertEqual(len(from_team), 1)
            self.assertEqual(from_team[0].description, "catalog desc")
            self.assertEqual(from_team[0].base_system_prompt, "catalog prompt")


if __name__ == "__main__":
    unittest.main()
