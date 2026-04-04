from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.use_cases.team_roles import set_team_role_enabled
from app.storage import Storage, StorageTransactionRequiredError


class LTC56StorageUoWGuardTests(unittest.TestCase):
    def test_write_outside_transaction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            storage.enable_write_uow_guard()

            with self.assertRaises(StorageTransactionRequiredError):
                storage.upsert_user(telegram_user_id=1, username="u1")

    def test_write_inside_transaction_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            storage.enable_write_uow_guard()

            with storage.transaction(immediate=True):
                storage.upsert_user(telegram_user_id=2, username="u2")

            got = storage.get_user(2)
            self.assertIsNotNone(got)
            self.assertEqual(got.telegram_user_id, 2)

    def test_team_roles_use_case_remains_compatible_with_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-5601, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="ltc56_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role.role_id)

            storage.enable_write_uow_guard()
            state = set_team_role_enabled(storage, group_id=group.group_id, role_id=role.role_id, enabled=False)

            self.assertFalse(state.enabled)

    def test_no_partial_write_on_mid_failure_user_and_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            storage.enable_write_uow_guard()

            with self.assertRaises(RuntimeError):
                with storage.transaction(immediate=True):
                    storage.upsert_user(telegram_user_id=3, username="u3")
                    storage.upsert_auth_token(telegram_user_id=3, encrypted_token="enc")
                    raise RuntimeError("boom")

            self.assertIsNone(storage.get_user(3))
            self.assertIsNone(storage.get_auth_token(3))

    def test_no_partial_write_on_mid_failure_provider_team_role_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-5602, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="ltc56_role_provider",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)
            storage.enable_write_uow_guard()

            with self.assertRaises(RuntimeError):
                with storage.transaction(immediate=True):
                    storage.set_provider_user_value_by_team_role("skills", "root_dir", team_role_id, "/tmp/root")
                    storage.set_user_authorized(telegram_user_id=10, is_authorized=True)
                    raise RuntimeError("boom")

            self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id))
            self.assertIsNone(storage.get_user(10))


if __name__ == "__main__":
    unittest.main()
