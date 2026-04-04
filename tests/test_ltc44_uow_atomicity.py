from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.use_cases.team_roles import (
    delete_team_role_binding_result,
    reset_team_role_session_result,
    upsert_provider_field_by_team_role_result,
    upsert_user_role_session_result,
)
from app.storage import Storage


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LTC44StorageTransactionTests(unittest.TestCase):
    def test_transaction_commit_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            cur = storage._conn.cursor()  # noqa: SLF001 - explicit low-level UoW test.

            with storage.transaction(immediate=True):
                cur.execute(
                    """
                    INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("provider", "k_commit", 1, "v1", _now_iso(), _now_iso()),
                )

            self.assertEqual(storage.get_provider_user_value("provider", "k_commit", 1), "v1")

            with self.assertRaises(RuntimeError):
                with storage.transaction(immediate=True):
                    cur.execute(
                        """
                        INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        ("provider", "k_rollback", 1, "v2", _now_iso(), _now_iso()),
                    )
                    raise RuntimeError("boom")

            self.assertIsNone(storage.get_provider_user_value("provider", "k_rollback", 1))

    def test_nested_transaction_uses_savepoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            cur = storage._conn.cursor()  # noqa: SLF001 - explicit low-level UoW test.

            with storage.transaction(immediate=True):
                cur.execute(
                    """
                    INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("provider", "outer_before", 1, "v1", _now_iso(), _now_iso()),
                )
                with self.assertRaises(RuntimeError):
                    with storage.transaction():
                        cur.execute(
                            """
                            INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            ("provider", "inner_fail", 1, "v2", _now_iso(), _now_iso()),
                        )
                        raise RuntimeError("inner boom")
                cur.execute(
                    """
                    INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("provider", "outer_after", 1, "v3", _now_iso(), _now_iso()),
                )

            self.assertEqual(storage.get_provider_user_value("provider", "outer_before", 1), "v1")
            self.assertIsNone(storage.get_provider_user_value("provider", "inner_fail", 1))
            self.assertEqual(storage.get_provider_user_value("provider", "outer_after", 1), "v3")


class LTC44AtomicUseCasesTests(unittest.TestCase):
    def _setup_team_role(self) -> tuple[Storage, int, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "test.sqlite3")
        group = storage.upsert_group(-2101, "g")
        team_id = int(group.team_id or 0)
        role = storage.upsert_role(
            role_name="ltc44_role",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
        return storage, group.group_id, role.role_id, int(team_role.team_role_id or 0)

    def test_reset_session_rolls_back_on_mid_failure(self) -> None:
        storage, group_id, role_id, team_role_id = self._setup_team_role()
        storage.save_user_role_session_by_team_role(telegram_user_id=101, team_role_id=team_role_id, session_id="s1")
        storage.set_provider_user_value_by_team_role("skills", "root_dir", team_role_id, "/tmp/root")

        runtime = SimpleNamespace(default_provider_id="skills", provider_registry={})
        with patch.object(storage, "list_provider_user_legacy_keys_for_role", side_effect=RuntimeError("mid-fail")):
            result = reset_team_role_session_result(runtime, storage, group_id=group_id, role_id=role_id, user_id=101)

        self.assertTrue(result.is_error)
        self.assertIsNotNone(storage.get_user_role_session_by_team_role(101, team_role_id))
        self.assertEqual(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id), "/tmp/root")

    def test_delete_binding_rolls_back_on_mid_failure(self) -> None:
        storage, group_id, role_id, team_role_id = self._setup_team_role()
        team_id = storage.resolve_team_id_by_telegram_chat(group_id)
        self.assertIsNotNone(team_id)
        storage.save_user_role_session_by_team_role(telegram_user_id=102, team_role_id=team_role_id, session_id="s2")
        storage.set_provider_user_value_by_team_role("provider", "working_dir", team_role_id, "/tmp/wd")

        runtime = SimpleNamespace(provider_registry={})
        with patch.object(storage, "list_provider_user_legacy_keys_for_role", side_effect=RuntimeError("mid-fail")):
            result = delete_team_role_binding_result(runtime, storage, group_id=group_id, role_id=role_id, user_id=102)

        self.assertTrue(result.is_error)
        self.assertTrue(storage.get_team_role(int(team_id), role_id).is_active)
        self.assertIsNotNone(storage.get_user_role_session_by_team_role(102, team_role_id))
        self.assertEqual(storage.get_provider_user_value_by_team_role("provider", "working_dir", team_role_id), "/tmp/wd")

    def test_session_field_upsert_rolls_back_when_result_construction_fails(self) -> None:
        storage, group_id, role_id, team_role_id = self._setup_team_role()
        self.assertIsNone(storage.get_user_role_session_by_team_role(103, team_role_id))

        with patch("app.core.use_cases.team_roles.Result.ok", side_effect=RuntimeError("result-fail")):
            result = upsert_user_role_session_result(
                storage,
                user_id=103,
                group_id=group_id,
                role_id=role_id,
                session_id="session-103",
            )

        self.assertTrue(result.is_error)
        self.assertIsNone(storage.get_user_role_session_by_team_role(103, team_role_id))

    def test_provider_field_upsert_rolls_back_when_result_construction_fails(self) -> None:
        storage, group_id, role_id, team_role_id = self._setup_team_role()
        self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id))

        with patch("app.core.use_cases.team_roles.Result.ok", side_effect=RuntimeError("result-fail")):
            result = upsert_provider_field_by_team_role_result(
                storage,
                group_id=group_id,
                role_id=role_id,
                provider_id="skills",
                key="root_dir",
                value="/tmp/root",
            )

        self.assertTrue(result.is_error)
        self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id))


if __name__ == "__main__":
    unittest.main()
