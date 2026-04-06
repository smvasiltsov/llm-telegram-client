from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.use_cases.read_api import (
    list_roles_catalog_errors_result,
    list_roles_catalog_result,
    list_team_sessions_result,
)
from app.role_catalog import RoleCatalog
from app.storage import Storage


class LTC72ReadApiExtensionUseCasesTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, SimpleNamespace, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        catalog_dir = root / "roles"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "dev.json").write_text(
            (
                '{"schema_version":1,"role_name":"DEVX","description":"Developer",'
                '"base_system_prompt":"p","extra_instruction":"i","llm_model":"gpt","is_active":true}\n'
            ),
            encoding="utf-8",
        )
        (catalog_dir / "broken.json").write_text("{", encoding="utf-8")
        runtime = SimpleNamespace(role_catalog=RoleCatalog.load(catalog_dir))
        storage = Storage(root / "ltc72.sqlite3")
        storage.attach_role_catalog(runtime.role_catalog)

        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9720, "g")
            dev = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            legacy = storage.upsert_role(
                role_name="legacy_missing",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, dev.role_id)
            storage.ensure_group_role(group.group_id, legacy.role_id)
            team_id = int(group.team_id or 0)
            storage.set_team_role_mode(team_id, dev.role_id, "orchestrator")
            storage.save_user_role_session_by_team(telegram_user_id=1, team_id=team_id, role_id=dev.role_id, session_id="s-dev")
            storage.save_user_role_session_by_team(telegram_user_id=2, team_id=team_id, role_id=legacy.role_id, session_id="s-legacy")
        return storage, runtime, team_id, dev.role_id

    def test_list_roles_catalog_result_supports_orchestrator_flags_and_pagination(self) -> None:
        storage, runtime, _, _ = self._bootstrap()
        result = list_roles_catalog_result(runtime, storage, include_inactive=False, limit=1, offset=0)
        self.assertTrue(result.is_ok)
        payload = result.value
        self.assertIsNotNone(payload)
        self.assertEqual(payload.total, 1)
        self.assertEqual(len(payload.items), 1)
        item = payload.items[0]
        self.assertEqual(item.role_name, "dev")
        self.assertTrue(item.is_orchestrator)
        self.assertTrue(item.has_errors)

    def test_list_roles_catalog_errors_includes_catalog_and_domain_mismatch(self) -> None:
        storage, runtime, _, _ = self._bootstrap()
        result = list_roles_catalog_errors_result(runtime, storage)
        self.assertTrue(result.is_ok)
        errors = result.value or []
        self.assertTrue(any(err.code == "invalid_json" for err in errors))
        self.assertTrue(any(err.code == "domain.role_missing_in_catalog" and err.role_name == "legacy_missing" for err in errors))

    def test_list_team_sessions_result_returns_required_fields(self) -> None:
        storage, _, team_id, _ = self._bootstrap()
        result = list_team_sessions_result(storage, team_id=team_id, limit=10, offset=0)
        self.assertTrue(result.is_ok)
        payload = result.value
        self.assertIsNotNone(payload)
        self.assertEqual(payload.total, 2)
        self.assertTrue(all(item.session_id for item in payload.items))
        self.assertTrue(all(item.updated_at for item in payload.items))
        self.assertTrue(any(item.team_role_id is not None for item in payload.items))

    def test_list_team_sessions_result_maps_missing_team_to_not_found(self) -> None:
        storage, _, _, _ = self._bootstrap()
        result = list_team_sessions_result(storage, team_id=999999, limit=10, offset=0)
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "storage.not_found")


if __name__ == "__main__":
    unittest.main()
