from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.role_catalog import RoleCatalog
from app.role_catalog_service import ensure_role_identity_by_name, list_active_master_role_names, refresh_role_catalog
from app.storage import Storage


class LTC12HotReloadFullScenarioTests(unittest.TestCase):
    def test_add_json_role_visible_after_refresh_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))
            storage = Storage(Path(td) / "test.sqlite3")

            self.assertEqual(list_active_master_role_names(runtime), [])

            self._write_role(
                root / "hot_add.json",
                role_name="hot_add",
                prompt="p",
                instruction="i",
            )
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]
            self.assertIn("hot_add", list_active_master_role_names(runtime))

    def test_remove_json_role_hides_from_list_and_cleans_team_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))
            team = storage.upsert_group(-100991, "g")
            team_id = team.team_id or 0

            role_file = root / "hot_remove.json"
            self._write_role(role_file, role_name="hot_remove", prompt="p", instruction="i")
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]
            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="hot_remove",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            self.assertTrue(storage.get_team_role(team_id, role.role_id).is_active)

            role_file.unlink()
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]

            self.assertNotIn("hot_remove", list_active_master_role_names(runtime))
            self.assertFalse(storage.get_team_role(team_id, role.role_id).is_active)

    def test_rename_to_invalid_file_name_deactivates_old_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))
            team = storage.upsert_group(-100992, "g")
            team_id = team.team_id or 0
            role_file = root / "rename_me.json"
            self._write_role(role_file, role_name="rename_me", prompt="p", instruction="i")
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]
            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="rename_me",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            role_file.rename(root / "Rename-Me.json")
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]
            self.assertNotIn("rename_me", list_active_master_role_names(runtime))
            self.assertFalse(storage.get_team_role(team_id, role.role_id).is_active)

    def test_invalid_json_does_not_break_valid_roles_listing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            storage = Storage(Path(td) / "test.sqlite3")
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))

            self._write_role(
                root / "valid_role.json",
                role_name="valid_role",
                prompt="p",
                instruction="i",
            )
            (root / "broken.json").write_text("{", encoding="utf-8")
            refresh_role_catalog(runtime=runtime, storage=storage)  # type: ignore[arg-type]

            self.assertIn("valid_role", list_active_master_role_names(runtime))
            self.assertGreaterEqual(len(runtime.role_catalog.issues), 1)
            self.assertTrue(any("invalid_json" in issue.reason for issue in runtime.role_catalog.issues))

    @staticmethod
    def _write_role(path: Path, *, role_name: str, prompt: str, instruction: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role_name": role_name,
                    "description": "",
                    "base_system_prompt": prompt,
                    "extra_instruction": instruction,
                    "llm_model": None,
                    "is_active": True,
                }
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
