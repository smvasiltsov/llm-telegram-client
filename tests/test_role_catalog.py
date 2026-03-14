from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.role_catalog import RoleCatalog


class RoleCatalogTests(unittest.TestCase):
    def test_load_catalog_with_valid_and_invalid_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "analyst.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            (root / "broken.json").write_text("{", encoding="utf-8")
            (root / "bad_schema.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "description": "d",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )

            catalog = RoleCatalog.load(root)
            self.assertEqual([r.role_name for r in catalog.list_all()], ["analyst"])
            self.assertEqual([r.role_name for r in catalog.list_active()], ["analyst"])
            self.assertGreaterEqual(len(catalog.issues), 2)

    def test_duplicate_role_name_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 1,
                "description": "d",
                "base_system_prompt": "sp",
                "extra_instruction": "ei",
                "llm_model": None,
                "is_active": True,
            }
            (root / "dev.json").write_text(json.dumps(payload), encoding="utf-8")
            (root / "DEV.json").write_text(json.dumps(payload), encoding="utf-8")

            catalog = RoleCatalog.load(root)
            self.assertEqual(len(catalog.list_all()), 0)
            self.assertTrue(any("duplicate_role_name_casefold" in issue.reason for issue in catalog.issues))

    def test_alias_fields_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "writer.json").write_text(
                json.dumps(
                    {
                        "role_name": "Writer",
                        "system_prompt": "prompt from alias",
                        "instruction": "instruction from alias",
                        "model": "provider:model-a",
                        "active": True,
                    }
                ),
                encoding="utf-8",
            )

            catalog = RoleCatalog.load(root)
            role = catalog.get("writer")
            self.assertIsNotNone(role)
            assert role is not None
            self.assertEqual(role.base_system_prompt, "prompt from alias")
            self.assertEqual(role.extra_instruction, "instruction from alias")
            self.assertEqual(role.llm_model, "provider:model-a")
            self.assertTrue(role.is_active)

    def test_get_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "qa.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "description": "",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            self.assertIsNotNone(catalog.get("QA"))

    def test_file_name_is_identity_and_json_role_name_is_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "from_file.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role_name": "from_payload",
                        "description": "",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            self.assertIsNotNone(catalog.get("from_file"))
            self.assertIsNone(catalog.get("from_payload"))
            self.assertTrue(any("role_name_mismatch" in issue.reason for issue in catalog.issues))

    def test_invalid_basename_blocks_loading(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "My-Role.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "description": "",
                        "base_system_prompt": "sp",
                        "extra_instruction": "ei",
                        "llm_model": None,
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            self.assertEqual(catalog.list_all(), [])
            self.assertTrue(any("invalid_file_name" in issue.reason for issue in catalog.issues))


if __name__ == "__main__":
    unittest.main()
