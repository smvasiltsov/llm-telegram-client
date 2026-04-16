from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.application.use_cases.transaction_boundaries import MANDATORY_STAGE3_TRANSACTION_BOUNDARIES
from app.application.use_cases.write_api import (
    TeamRenameRequest,
    TeamRolePrepostReplaceItem,
    TeamRolePrepostReplaceRequest,
    TeamRoleSkillReplaceItem,
    TeamRoleSkillsReplaceRequest,
    delete_master_role_result,
    delete_team_result,
    MasterRoleCreateRequest,
    TeamCreateRequest,
    TeamRolePatchRequest,
    TeamRolePrepostPutRequest,
    TeamRoleRootDirPutRequest,
    TeamRoleSkillPutRequest,
    TeamRoleWorkingDirPutRequest,
    create_master_role_result,
    create_team_result,
    rename_team_result,
    deactivate_team_role_binding_write_result,
    patch_team_role_result,
    replace_team_role_prepost_result,
    replace_team_role_skills_result,
    put_team_role_prepost_result,
    put_team_role_root_dir_result,
    put_team_role_skill_result,
    put_team_role_working_dir_result,
    reset_team_role_session_write_result,
)
from app.storage import Storage


class _FakeSkillRegistry:
    def __init__(self) -> None:
        self._known = {"fs.list_dir": object(), "fs.read_file": object()}

    def get(self, skill_id: str):
        return self._known.get(skill_id)


class _FakePrepostRegistry:
    def __init__(self) -> None:
        self._known = {"echo": object(), "trim": object()}

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

    def test_replace_team_role_skills_full_replace_and_empty_clear(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(skills_registry=_FakeSkillRegistry())
        first = replace_team_role_skills_result(
            runtime,
            storage,
            request=TeamRoleSkillsReplaceRequest(
                team_role_id=team_role_id,
                items=(
                    TeamRoleSkillReplaceItem(skill_id="fs.list_dir", enabled=True, config={"root_dir": "/tmp"}),
                    TeamRoleSkillReplaceItem(skill_id="fs.read_file", enabled=False, config={"x": 1}),
                ),
            ),
        )
        second = replace_team_role_skills_result(
            runtime,
            storage,
            request=TeamRoleSkillsReplaceRequest(
                team_role_id=team_role_id,
                items=(TeamRoleSkillReplaceItem(skill_id="fs.read_file", enabled=True, config={"x": 2}),),
            ),
        )
        clear = replace_team_role_skills_result(
            runtime,
            storage,
            request=TeamRoleSkillsReplaceRequest(team_role_id=team_role_id, items=()),
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(clear.is_ok)
        assert second.value is not None
        self.assertEqual([item.skill_id for item in second.value.items], ["fs.read_file"])
        assert clear.value is not None
        self.assertEqual(list(clear.value.items), [])

    def test_replace_team_role_skills_duplicate_and_unknown(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(skills_registry=_FakeSkillRegistry())
        duplicate = replace_team_role_skills_result(
            runtime,
            storage,
            request=TeamRoleSkillsReplaceRequest(
                team_role_id=team_role_id,
                items=(
                    TeamRoleSkillReplaceItem(skill_id="fs.list_dir"),
                    TeamRoleSkillReplaceItem(skill_id="fs.list_dir"),
                ),
            ),
        )
        unknown = replace_team_role_skills_result(
            runtime,
            storage,
            request=TeamRoleSkillsReplaceRequest(
                team_role_id=team_role_id,
                items=(TeamRoleSkillReplaceItem(skill_id="fs.unknown"),),
            ),
        )
        self.assertTrue(duplicate.is_error)
        self.assertEqual((duplicate.error.code if duplicate.error else None), "validation.invalid_input")
        self.assertTrue(unknown.is_error)
        self.assertEqual((unknown.error.code if unknown.error else None), "storage.not_found")

    def test_replace_team_role_prepost_full_replace_and_empty_clear(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(prepost_processing_registry=_FakePrepostRegistry())
        first = replace_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostReplaceRequest(
                team_role_id=team_role_id,
                items=(
                    TeamRolePrepostReplaceItem(prepost_id="echo", enabled=True, config={"x": 1}),
                    TeamRolePrepostReplaceItem(prepost_id="trim", enabled=False, config={"y": 2}),
                ),
            ),
        )
        second = replace_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostReplaceRequest(
                team_role_id=team_role_id,
                items=(TeamRolePrepostReplaceItem(prepost_id="trim", enabled=True, config={"y": 3}),),
            ),
        )
        clear = replace_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostReplaceRequest(team_role_id=team_role_id, items=()),
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(clear.is_ok)
        assert second.value is not None
        self.assertEqual([item.prepost_id for item in second.value.items], ["trim"])
        assert clear.value is not None
        self.assertEqual(list(clear.value.items), [])

    def test_replace_team_role_prepost_duplicate_and_unknown(self) -> None:
        storage, _, _, team_role_id = self._bootstrap()
        runtime = SimpleNamespace(prepost_processing_registry=_FakePrepostRegistry())
        duplicate = replace_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostReplaceRequest(
                team_role_id=team_role_id,
                items=(
                    TeamRolePrepostReplaceItem(prepost_id="echo"),
                    TeamRolePrepostReplaceItem(prepost_id="echo"),
                ),
            ),
        )
        unknown = replace_team_role_prepost_result(
            runtime,
            storage,
            request=TeamRolePrepostReplaceRequest(
                team_role_id=team_role_id,
                items=(TeamRolePrepostReplaceItem(prepost_id="unknown"),),
            ),
        )
        self.assertTrue(duplicate.is_error)
        self.assertEqual((duplicate.error.code if duplicate.error else None), "validation.invalid_input")
        self.assertTrue(unknown.is_error)
        self.assertEqual((unknown.error.code if unknown.error else None), "storage.not_found")

    def test_create_master_role_happy_path_and_duplicate_conflict(self) -> None:
        storage, _, _, _ = self._bootstrap()
        first = create_master_role_result(
            storage,
            request=MasterRoleCreateRequest(
                role_name="new_master",
                system_prompt="You are new master",
                llm_model="gpt-4o-mini",
                description="desc",
                extra_instruction="extra",
            ),
        )
        duplicate = create_master_role_result(
            storage,
            request=MasterRoleCreateRequest(
                role_name="new_master",
                system_prompt="Another prompt",
                llm_model="gpt-4o-mini",
            ),
        )
        self.assertTrue(first.is_ok)
        assert first.value is not None
        self.assertEqual(first.value.role_name, "new_master")
        self.assertTrue(first.value.is_active)
        self.assertTrue(duplicate.is_error)
        self.assertEqual((duplicate.error.code if duplicate.error else None), "conflict.already_exists")

    def test_create_master_role_validation(self) -> None:
        storage, _, _, _ = self._bootstrap()
        bad_role_name = create_master_role_result(
            storage,
            request=MasterRoleCreateRequest(
                role_name=" ",
                system_prompt="sp",
                llm_model="m",
            ),
        )
        bad_prompt = create_master_role_result(
            storage,
            request=MasterRoleCreateRequest(
                role_name="x1",
                system_prompt="",
                llm_model="m",
            ),
        )
        bad_model = create_master_role_result(
            storage,
            request=MasterRoleCreateRequest(
                role_name="x2",
                system_prompt="sp",
                llm_model=" ",
            ),
        )
        self.assertTrue(bad_role_name.is_error)
        self.assertTrue(bad_prompt.is_error)
        self.assertTrue(bad_model.is_error)
        self.assertEqual((bad_role_name.error.code if bad_role_name.error else None), "validation.invalid_input")
        self.assertEqual((bad_prompt.error.code if bad_prompt.error else None), "validation.invalid_input")
        self.assertEqual((bad_model.error.code if bad_model.error else None), "validation.invalid_input")

    def test_create_team_happy_path_and_validation(self) -> None:
        storage, _, _, _ = self._bootstrap()
        ok = create_team_result(storage, request=TeamCreateRequest(name="Team Alpha"))
        bad = create_team_result(storage, request=TeamCreateRequest(name=" "))
        self.assertTrue(ok.is_ok)
        assert ok.value is not None
        self.assertTrue(str(ok.value.public_id).startswith("team-"))
        self.assertEqual(ok.value.name, "Team Alpha")
        self.assertTrue(bad.is_error)
        self.assertEqual((bad.error.code if bad.error else None), "validation.invalid_input")

    def test_rename_team_happy_path_and_422(self) -> None:
        storage, team_id, _, _ = self._bootstrap()
        ok = rename_team_result(storage, team_id=team_id, request=TeamRenameRequest(name="Renamed Team"))
        bad = rename_team_result(storage, team_id=team_id, request=TeamRenameRequest(name="  "))
        self.assertTrue(ok.is_ok)
        assert ok.value is not None
        self.assertEqual(ok.value.name, "Renamed Team")
        self.assertTrue(bad.is_error)
        self.assertEqual((bad.error.code if bad.error else None), "validation.invalid_input")

    def test_delete_team_returns_404_and_409_when_team_has_dependencies(self) -> None:
        storage, _, _, _ = self._bootstrap()
        missing = delete_team_result(storage, team_id=999999)
        self.assertTrue(missing.is_error)
        self.assertEqual((missing.error.code if missing.error else None), "storage.not_found")

        created = create_team_result(storage, request=TeamCreateRequest(name="Delete Me"))
        self.assertTrue(created.is_ok)
        assert created.value is not None
        team_id = int(created.value.team_id)
        with storage.transaction(immediate=True):
            role = storage.upsert_role(
                role_name="for_delete_team_conflict",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, int(role.role_id))
        conflict = delete_team_result(storage, team_id=team_id)
        self.assertTrue(conflict.is_error)
        self.assertEqual((conflict.error.code if conflict.error else None), "conflict.already_exists")

    def test_delete_master_role_returns_404_and_409_when_role_in_use(self) -> None:
        storage, _, role_id, _ = self._bootstrap()
        missing = delete_master_role_result(storage, role_id=999999)
        self.assertTrue(missing.is_error)
        self.assertEqual((missing.error.code if missing.error else None), "storage.not_found")

        in_use = delete_master_role_result(storage, role_id=role_id)
        self.assertTrue(in_use.is_error)
        self.assertEqual((in_use.error.code if in_use.error else None), "conflict.already_exists")


if __name__ == "__main__":
    unittest.main()
