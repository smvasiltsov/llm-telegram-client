from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.use_cases.read_api import (
    list_team_roles_result,
    list_team_runtime_status_result,
    list_teams_result,
)
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage


class LTC69ReadOnlyApiUseCasesTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc69.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9691, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = storage.resolve_team_role_id(int(group.team_id or 0), role.role_id, ensure_exists=True)
            if team_role_id is None:
                raise AssertionError("team_role_id missing")
            storage.ensure_team_role_runtime_status(int(team_role_id))
        return storage, int(group.team_id or 0), int(team_role_id)

    def test_list_teams_result_returns_active_teams(self) -> None:
        storage, team_id, _ = self._bootstrap()
        result = list_teams_result(storage)
        self.assertTrue(result.is_ok)
        self.assertTrue(any(team.team_id == team_id for team in (result.value or [])))

    def test_list_team_roles_result_returns_roles_for_team(self) -> None:
        storage, team_id, _ = self._bootstrap()
        result = list_team_roles_result(storage, team_id=team_id)
        self.assertTrue(result.is_ok)
        role_names = [role.role_name for role in (result.value or [])]
        self.assertIn("dev", role_names)

    def test_list_team_roles_result_includes_orchestrator_flag(self) -> None:
        storage, team_id, _ = self._bootstrap()
        with storage.transaction(immediate=True):
            role = storage.get_role_by_name("dev")
            storage.set_team_role_mode(team_id, role.role_id, "orchestrator")
        result = list_team_roles_result(storage, team_id=team_id)
        self.assertTrue(result.is_ok)
        self.assertTrue(any(getattr(role, "is_orchestrator", False) for role in (result.value or [])))

    def test_list_team_roles_result_include_inactive_returns_disabled(self) -> None:
        storage, team_id, _ = self._bootstrap()
        with storage.transaction(immediate=True):
            role = storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            storage.deactivate_team_role(team_id, role.role_id)
        active_only = list_team_roles_result(storage, team_id=team_id, include_inactive=False)
        include_inactive = list_team_roles_result(storage, team_id=team_id, include_inactive=True)
        self.assertTrue(active_only.is_ok)
        self.assertTrue(include_inactive.is_ok)
        self.assertFalse(any(role.role_name == "ops" for role in (active_only.value or [])))
        self.assertTrue(any(role.role_name == "ops" and role.is_active is False for role in (include_inactive.value or [])))

    def test_list_team_runtime_status_result_returns_status_rows(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
        result = list_team_runtime_status_result(storage, service, team_id=team_id)
        self.assertTrue(result.is_ok)
        ids = [row.team_role_id for row in (result.value or [])]
        self.assertIn(team_role_id, ids)

    def test_read_only_use_cases_map_missing_team_to_storage_not_found(self) -> None:
        storage, _, _ = self._bootstrap()
        service = RoleRuntimeStatusService(storage, free_transition_delay_sec=0)
        roles_result = list_team_roles_result(storage, team_id=999_999)
        statuses_result = list_team_runtime_status_result(storage, service, team_id=999_999)
        self.assertTrue(roles_result.is_error)
        self.assertEqual((roles_result.error.code if roles_result.error else None), "storage.not_found")
        self.assertEqual((roles_result.error.http_status if roles_result.error else None), 404)
        self.assertTrue(statuses_result.is_error)
        self.assertEqual((statuses_result.error.code if statuses_result.error else None), "storage.not_found")
        self.assertEqual((statuses_result.error.http_status if statuses_result.error else None), 404)


if __name__ == "__main__":
    unittest.main()
