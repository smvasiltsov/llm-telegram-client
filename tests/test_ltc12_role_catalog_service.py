from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.role_catalog import RoleCatalog
from app.role_catalog_service import create_master_role_json, ensure_role_identity_by_name, refresh_role_catalog
from app.storage import Storage


class LTC12RoleCatalogServiceTests(unittest.TestCase):
    def test_create_master_role_json_and_ensure_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))

            role_id = create_master_role_json(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="new_master",
                base_system_prompt="p",
                extra_instruction="i",
                llm_model=None,
            )
            self.assertGreater(role_id, 0)
            self.assertTrue((root / "new_master.json").exists())
            self.assertIsNotNone(runtime.role_catalog.get("new_master"))

            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="new_master",
            )
            self.assertEqual(role.role_name, "new_master")
            self.assertEqual(role.role_id, role_id)

    def test_refresh_deactivates_team_bindings_when_role_file_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-100881, "team")
            team_id = group.team_id or 0
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            role_json = root / "to_delete.json"
            role_json.write_text(
                '{"schema_version":1,"role_name":"to_delete","description":"","base_system_prompt":"p","extra_instruction":"i","llm_model":null,"is_active":true}\n',
                encoding="utf-8",
            )
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))
            storage.attach_role_catalog(runtime.role_catalog)
            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="to_delete",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            self.assertTrue(storage.get_team_role(team_id, role.role_id).is_active)

            role_json.unlink()
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]

            self.assertIsNone(runtime.role_catalog.get("to_delete"))
            self.assertFalse(storage.get_team_role(team_id, role.role_id).is_active)


if __name__ == "__main__":
    unittest.main()
