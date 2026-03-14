from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.role_catalog_export import export_roles_from_db_first_run
from app.storage import Storage


class RoleCatalogExportTests(unittest.TestCase):
    def test_first_run_exports_roles_and_writes_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            storage.upsert_role(
                role_name="role_for_export",
                description="desc",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )

            root = Path(td) / "roles_catalog"
            result = export_roles_from_db_first_run(storage, root)

            self.assertTrue(result.marker_created)
            self.assertFalse(result.skipped_by_marker)
            self.assertEqual(result.exported_count, 1)
            self.assertEqual(result.conflict_count, 0)
            self.assertEqual(result.invalid_count, 0)
            self.assertTrue((root / "role_for_export.json").exists())
            self.assertTrue((root / ".migration" / "db_export_v1.done.json").exists())
            self.assertTrue(result.report_path.exists())

            payload = json.loads((root / "role_for_export.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["role_name"], "role_for_export")
            self.assertEqual(payload["llm_model"], "provider:model")

    def test_existing_json_wins_and_is_logged_as_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            storage.upsert_role(
                role_name="analyst",
                description="db desc",
                base_system_prompt="db sp",
                extra_instruction="db ei",
                llm_model=None,
                is_active=True,
            )

            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "analyst.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role_name": "analyst",
                        "description": "file desc",
                        "base_system_prompt": "file sp",
                        "extra_instruction": "file ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )

            result = export_roles_from_db_first_run(storage, root)
            self.assertEqual(result.exported_count, 0)
            self.assertEqual(result.conflict_count, 1)
            self.assertTrue(result.conflict_log_path.exists())
            log_lines = result.conflict_log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(log_lines), 1)
            row = json.loads(log_lines[0])
            self.assertEqual(row["event"], "conflict_existing_json")
            self.assertEqual(row["role_name"], "analyst")

    def test_marker_makes_export_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            storage.upsert_role(
                role_name="first",
                description="d1",
                base_system_prompt="sp1",
                extra_instruction="ei1",
                llm_model=None,
                is_active=True,
            )
            root = Path(td) / "roles_catalog"
            first = export_roles_from_db_first_run(storage, root)
            self.assertEqual(first.exported_count, 1)

            storage.upsert_role(
                role_name="second",
                description="d2",
                base_system_prompt="sp2",
                extra_instruction="ei2",
                llm_model=None,
                is_active=True,
            )
            second = export_roles_from_db_first_run(storage, root)
            self.assertTrue(second.skipped_by_marker)
            self.assertEqual(second.exported_count, 0)
            self.assertFalse((root / "second.json").exists())


if __name__ == "__main__":
    unittest.main()
