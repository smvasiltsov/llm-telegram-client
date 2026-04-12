from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.application.use_cases.transaction_boundaries import MANDATORY_STAGE3_TRANSACTION_BOUNDARIES
from app.application.use_cases.write_api import (
    TeamRolePatchRequest,
    TeamRolePrepostPutRequest,
    TeamRoleRootDirPutRequest,
    TeamRoleSkillPutRequest,
    TeamRoleWorkingDirPutRequest,
    deactivate_team_role_binding_write_result,
    patch_team_role_result,
    put_team_role_prepost_result,
    put_team_role_root_dir_result,
    put_team_role_skill_result,
    put_team_role_working_dir_result,
    reset_team_role_session_write_result,
)
from app.storage import Storage


class _FakeSkillRegistry:
    def __init__(self) -> None:
        self._known = {"fs.list_dir": object()}

    def get(self, skill_id: str):
        return self._known.get(skill_id)


class _FakePrepostRegistry:
    def __init__(self) -> None:
        self._known = {"echo": object()}

    def get(self, prepost_id: str):
        return self._known.get(prepost_id)


class LTC73WriteApiUseCasesTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc73.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9731, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(int(group.team_id or 0), role.role_id)
            if team_role.team_role_id is None:
                raise AssertionError("team_role_id missing")
            storage.save_user_role_session_by_team_role(telegram_user_id=42, team_role_id=team_role.team_role_id, session_id="s1")
        return storage, int(group.team_id or 0), role.role_id, int(team_role.team_role_id)

    def test_stage3_mandatory_boundary_registry_contains_required_scenarios(self) -> None:
        expected = {
            "reset session",
            "deactivate binding",
            "skill toggle",
            "prepost toggle/config-lite",
            "runtime status transitions",
        }
        actual = {item.scenario for item in MANDATORY_STAGE3_TRANSACTION_BOUNDARIES}
        self.assertEqual(actual, expected)

    def test_patch_team_role_result_updates_target_state(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original_set_enabled = storage.set_team_role_enabled

        def _wrapped_set_enabled(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original_set_enabled(*args, **kwargs)

        with patch.object(storage, "set_team_role_enabled", side_effect=_wrapped_set_enabled):
            result = patch_team_role_result(
                storage,
                team_role_id=team_role_id,
                patch=TeamRolePatchRequest(enabled=False, is_orchestrator=False, display_name="Dev Team"),
            )

        self.assertTrue(result.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))
        assert result.value is not None
        self.assertFalse(result.value.enabled)
        self.assertEqual(result.value.display_name, "Dev Team")

    def test_patch_team_role_rejects_conflicting_enabled_and_is_active(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        result = patch_team_role_result(
            storage,
            team_role_id=team_role_id,
            patch=TeamRolePatchRequest(enabled=True, is_active=False),
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "validation.invalid_input")

    def test_reset_session_write_is_idempotent_and_rejects_payload_mismatch(self) -> None:
        storage, team_id, role_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.set_team_role_working_dir_by_id(team_role_id, "/tmp/work")
            storage.set_team_role_root_dir_by_id(team_role_id, "/tmp/root")
        runtime = SimpleNamespace(provider_registry={})
        first = reset_team_role_session_write_result(
            runtime,
            storage,
            team_role_id=team_role_id,
            telegram_user_id=42,
            idempotency_key="k-reset-1",
        )
        second = reset_team_role_session_write_result(
            runtime,
            storage,
            team_role_id=team_role_id,
            telegram_user_id=42,
            idempotency_key="k-reset-1",
        )
        mismatch = reset_team_role_session_write_result(
            runtime,
            storage,
            team_role_id=team_role_id,
            telegram_user_id=43,
            idempotency_key="k-reset-1",
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(mismatch.is_error)
        self.assertEqual((mismatch.error.code if mismatch.error else None), "validation.invalid_input")
        state = storage.get_team_role(team_id, role_id)
        self.assertIsNone(state.working_dir)
        self.assertIsNone(state.root_dir)

    def test_reset_session_write_returns_not_found_for_invalid_telegram_user_id(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(provider_registry={})
        result = reset_team_role_session_write_result(
            runtime,
            storage,
            team_role_id=team_role_id,
            telegram_user_id=999999,
            idempotency_key="k-reset-missing-user",
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "storage.not_found")
        self.assertEqual((result.error.http_status if result.error else None), 404)

    def test_deactivate_binding_write_runs_inside_transaction(self) -> None:
        storage, team_id, role_id, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(provider_registry={})
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original = storage.get_team_role_by_id

        def _wrapped_get_team_role_by_id(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original(*args, **kwargs)

        with patch.object(storage, "get_team_role_by_id", side_effect=_wrapped_get_team_role_by_id):
            result = deactivate_team_role_binding_write_result(
                runtime,
                storage,
                team_role_id=team_role_id,
                telegram_user_id=42,
                idempotency_key="k-del-1",
            )

        self.assertTrue(result.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))
        with self.assertRaises(ValueError):
            _ = storage.get_team_role(team_id, role_id)

    def test_put_skill_runs_inside_transaction_and_is_state_idempotent(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(skills_registry=_FakeSkillRegistry())
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original_upsert = storage.upsert_role_skill_for_team_role

        def _wrapped_upsert(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original_upsert(*args, **kwargs)

        with patch.object(storage, "upsert_role_skill_for_team_role", side_effect=_wrapped_upsert):
            first = put_team_role_skill_result(
                runtime,
                storage,
                request=TeamRoleSkillPutRequest(
                    team_role_id=team_role_id,
                    skill_id="fs.list_dir",
                    enabled=True,
                    config={"root_dir": "/tmp"},
                ),
            )
        second = put_team_role_skill_result(
            runtime,
            storage,
            request=TeamRoleSkillPutRequest(
                team_role_id=team_role_id,
                skill_id="fs.list_dir",
                enabled=True,
                config={"root_dir": "/tmp"},
            ),
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))
        assert second.value is not None
        self.assertTrue(second.value.enabled)

    def test_put_prepost_runs_inside_transaction_and_updates_config(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(prepost_processing_registry=_FakePrepostRegistry())
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original_upsert = storage.upsert_role_prepost_processing_for_team_role

        def _wrapped_upsert(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original_upsert(*args, **kwargs)

        with patch.object(storage, "upsert_role_prepost_processing_for_team_role", side_effect=_wrapped_upsert):
            first = put_team_role_prepost_result(
                runtime,
                storage,
                request=TeamRolePrepostPutRequest(
                    team_role_id=team_role_id,
                    prepost_id="echo",
                    enabled=True,
                    config={"x": 1},
                ),
            )
        second = put_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostPutRequest(
                team_role_id=team_role_id,
                prepost_id="echo",
                enabled=False,
                config={"x": 2},
            ),
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))
        assert second.value is not None
        self.assertFalse(second.value.enabled)
        self.assertEqual(second.value.config, {"x": 2})

    def test_put_working_dir_requires_absolute_path_and_updates_team_role(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace()
        ok = put_team_role_working_dir_result(
            runtime,
            storage,
            request=TeamRoleWorkingDirPutRequest(
                team_role_id=team_role_id,
                working_dir="/tmp/work",
            ),
        )
        bad = put_team_role_working_dir_result(
            runtime,
            storage,
            request=TeamRoleWorkingDirPutRequest(
                team_role_id=team_role_id,
                working_dir="relative/path",
            ),
        )
        self.assertTrue(ok.is_ok)
        self.assertTrue(bad.is_error)
        self.assertEqual((bad.error.code if bad.error else None), "validation.invalid_input")
        assert ok.value is not None
        self.assertEqual(ok.value.working_dir, "/tmp/work")

    def test_put_root_dir_requires_absolute_path(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace()
        ok = put_team_role_root_dir_result(
            runtime,
            storage,
            request=TeamRoleRootDirPutRequest(
                team_role_id=team_role_id,
                root_dir="/tmp/root",
            ),
        )
        bad = put_team_role_root_dir_result(
            runtime,
            storage,
            request=TeamRoleRootDirPutRequest(
                team_role_id=team_role_id,
                root_dir="relative/path",
            ),
        )
        self.assertTrue(ok.is_ok)
        self.assertTrue(bad.is_error)
        self.assertEqual((bad.error.code if bad.error else None), "validation.invalid_input")
        assert ok.value is not None
        self.assertEqual(ok.value.root_dir, "/tmp/root")


if __name__ == "__main__":
    unittest.main()
