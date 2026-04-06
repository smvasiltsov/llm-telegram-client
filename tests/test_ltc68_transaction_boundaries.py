from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.application.use_cases.transaction_boundaries import (
    MANDATORY_STAGE2_TRANSACTION_BOUNDARIES,
    delete_team_role_binding_uow,
    pop_pending_replay_if_unchanged,
    reset_team_role_session_uow,
    toggle_team_role_skill_result,
)
from app.pending_store import PendingStore
from app.storage import Storage


class _FakeSkillsRegistry:
    def __init__(self) -> None:
        self._known = {"fs_list_dir": object()}

    def get(self, skill_id: str):
        return self._known.get(skill_id)


class LTC68TransactionBoundariesTests(unittest.TestCase):
    def _bootstrap_team_role(self) -> tuple[Storage, int, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc68.sqlite3")
        group = storage.upsert_group(-9681, "g")
        role = storage.upsert_role(
            role_name="role_a",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        team_role, _ = storage.bind_master_role_to_team(int(group.team_id or 0), role.role_id)
        if team_role.team_role_id is None:
            raise AssertionError("team_role_id missing")
        return storage, group.group_id, role.role_id, int(team_role.team_role_id)

    def test_stage2_mandatory_boundary_registry_contains_all_required_scenarios(self) -> None:
        required = {
            "reset session",
            "delete/deactivate binding",
            "pending replay",
            "skill toggle",
            "runtime status transitions",
        }
        actual = {item.scenario for item in MANDATORY_STAGE2_TRANSACTION_BOUNDARIES}
        self.assertEqual(actual, required)

    def test_reset_session_wrapper_runs_inside_transaction(self) -> None:
        storage, group_id, role_id, team_role_id = self._bootstrap_team_role()
        storage.save_user_role_session_by_team_role(telegram_user_id=1001, team_role_id=team_role_id, session_id="s1")
        runtime = SimpleNamespace(provider_registry={})
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original = storage.list_provider_user_legacy_keys_for_role

        def _wrapped(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original(*args, **kwargs)

        with patch.object(storage, "list_provider_user_legacy_keys_for_role", side_effect=_wrapped):
            result = reset_team_role_session_uow(runtime, storage, group_id=group_id, role_id=role_id, user_id=1001)

        self.assertTrue(result.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    def test_delete_binding_wrapper_runs_inside_transaction(self) -> None:
        storage, group_id, role_id, team_role_id = self._bootstrap_team_role()
        storage.save_user_role_session_by_team_role(telegram_user_id=1002, team_role_id=team_role_id, session_id="s1")
        runtime = SimpleNamespace(provider_registry={})
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original = storage.list_provider_user_legacy_keys_for_role

        def _wrapped(*args, **kwargs):
            observed_tx_depths.append(storage._tx_depth)
            return original(*args, **kwargs)

        with patch.object(storage, "list_provider_user_legacy_keys_for_role", side_effect=_wrapped):
            result = delete_team_role_binding_uow(runtime, storage, group_id=group_id, role_id=role_id, user_id=1002)

        self.assertTrue(result.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    def test_skill_toggle_runs_inside_transaction(self) -> None:
        storage, group_id, role_id, _ = self._bootstrap_team_role()
        storage.enable_write_uow_guard()
        observed_tx_depths: list[int] = []
        original_upsert = storage.upsert_role_skill_for_team_role

        def _wrapped_upsert(team_role_id: int, skill_id: str, *, enabled: bool, config):  # noqa: ANN001
            observed_tx_depths.append(storage._tx_depth)
            return original_upsert(team_role_id, skill_id, enabled=enabled, config=config)

        with patch.object(storage, "upsert_role_skill_for_team_role", side_effect=_wrapped_upsert):
            result = toggle_team_role_skill_result(
                storage=storage,
                skills_registry=_FakeSkillsRegistry(),
                group_id=group_id,
                role_id=role_id,
                skill_id="fs_list_dir",
            )

        self.assertTrue(result.is_ok)
        self.assertTrue(observed_tx_depths)
        self.assertTrue(all(depth > 0 for depth in observed_tx_depths))

    def test_pending_replay_pop_only_when_payload_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "pending.sqlite3"
            pending = PendingStore(db_path)
            pending.save(
                telegram_user_id=501,
                chat_id=-1,
                message_id=44,
                role_name="dev",
                content="ping",
                reply_text=None,
                team_id=7,
            )
            original = pending.peek_record(501)
            self.assertIsNotNone(original)
            assert original is not None

            removed, current = pop_pending_replay_if_unchanged(
                pending_store=pending,
                user_id=501,
                original_pending_msg=original,
            )
            self.assertTrue(removed)
            self.assertIsNone(current)
            self.assertIsNone(pending.peek_record(501))

            pending.save(
                telegram_user_id=501,
                chat_id=-1,
                message_id=45,
                role_name="ops",
                content="pong",
                reply_text=None,
                team_id=7,
            )
            stale_original = {
                "chat_id": -1,
                "team_id": 7,
                "message_id": 44,
                "role_name": "dev",
                "content": "ping",
                "reply_text": None,
            }
            removed, current = pop_pending_replay_if_unchanged(
                pending_store=pending,
                user_id=501,
                original_pending_msg=stale_original,
            )
            self.assertFalse(removed)
            self.assertIsNotNone(current)
            self.assertEqual((current or {}).get("role_name"), "ops")


if __name__ == "__main__":
    unittest.main()

