from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.use_cases.role_admin_view import build_master_roles_view, build_team_roles_view
from app.role_catalog import RoleCatalog
from app.storage import Storage


def _write_role_json(root: Path, role_name: str) -> None:
    payload = (
        "{\n"
        f'  "schema_version": 1,\n  "role_name": "{role_name}",\n'
        '  "description": "d",\n  "base_system_prompt": "sp",\n'
        '  "extra_instruction": "ei",\n  "llm_model": null,\n  "is_active": true\n}\n'
    )
    (root / f"{role_name}.json").write_text(payload, encoding="utf-8")


class LTC42RoleAdminViewUseCasesTests(unittest.TestCase):
    def test_build_master_roles_view_returns_text_and_names(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            catalog_dir = Path(td) / "roles_catalog"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            _write_role_json(catalog_dir, "dev")
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(catalog_dir))
            storage = Storage(Path(td) / "test.sqlite3")

            result = build_master_roles_view(runtime=runtime, storage=storage)

            self.assertTrue(result.is_ok)
            self.assertIsNotNone(result.value)
            assert result.value is not None
            self.assertIn("Выбери master-role", result.value.text)
            self.assertIn("dev", result.value.role_names)

    def test_build_team_roles_view_returns_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-4201, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)

            result = build_team_roles_view(storage=storage, group_id=group.group_id)

            self.assertTrue(result.is_ok)
            self.assertIsNotNone(result.value)
            assert result.value is not None
            self.assertEqual(result.value.group_id, group.group_id)
            self.assertEqual(len(result.value.roles), 1)
            self.assertEqual(result.value.roles[0].role_id, role.role_id)

    def test_build_team_roles_view_can_include_inactive_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-4202, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            with storage.transaction(immediate=True):
                storage.set_team_role_active(team_id, role.role_id, False)

            active_only = build_team_roles_view(storage=storage, group_id=group.group_id)
            with_inactive = build_team_roles_view(storage=storage, group_id=group.group_id, include_inactive=True)

            self.assertTrue(active_only.is_ok)
            self.assertTrue(with_inactive.is_ok)
            assert active_only.value is not None
            assert with_inactive.value is not None
            self.assertEqual(len(active_only.value.roles), 0)
            self.assertEqual(len(with_inactive.value.roles), 1)
            self.assertFalse(with_inactive.value.roles[0].is_active)
