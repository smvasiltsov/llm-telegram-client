from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.storage import Storage


class TeamMigrationAdditiveTests(unittest.TestCase):
    def test_storage_additive_team_migration_backfills_existing_group_data(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.sqlite3"
            self._create_legacy_schema_with_data(db_path)

            storage = Storage(db_path)
            _ = storage  # trigger migrations via __init__

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                self.assertTrue(self._has_table(conn, "teams"))
                self.assertTrue(self._has_table(conn, "team_bindings"))
                self.assertTrue(self._has_table(conn, "team_roles"))
                self.assertTrue(self._has_column(conn, "groups", "team_id"))
                self.assertTrue(self._has_column(conn, "user_role_sessions", "team_id"))

                row = conn.execute("SELECT team_id FROM groups WHERE group_id = -1001").fetchone()
                self.assertIsNotNone(row)
                team_id = row["team_id"]
                self.assertIsNotNone(team_id)

                binding = conn.execute(
                    "SELECT team_id, interface_type, external_id FROM team_bindings WHERE interface_type='telegram' AND external_id='-1001'"
                ).fetchone()
                self.assertIsNotNone(binding)
                self.assertEqual(binding["team_id"], team_id)

                team_role = conn.execute(
                    "SELECT team_id, role_id FROM team_roles WHERE team_id = ? AND role_id = 1",
                    (team_id,),
                ).fetchone()
                self.assertIsNotNone(team_role)

                session = conn.execute(
                    "SELECT team_id FROM user_role_sessions WHERE telegram_user_id = 42 AND group_id = -1001 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(session)
                self.assertEqual(session["team_id"], team_id)
            finally:
                conn.close()

    @staticmethod
    def _has_table(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)

    @staticmethod
    def _create_legacy_schema_with_data(db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE groups (
                    group_id INTEGER PRIMARY KEY,
                    title TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE roles (
                    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    base_system_prompt TEXT NOT NULL,
                    extra_instruction TEXT NOT NULL,
                    llm_model TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE group_roles (
                    group_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    system_prompt_override TEXT,
                    display_name TEXT,
                    model_override TEXT,
                    user_prompt_suffix TEXT,
                    user_reply_prefix TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'normal',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (group_id, role_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE user_role_sessions (
                    telegram_user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, group_id, role_id)
                )
                """
            )

            cur.execute(
                "INSERT INTO groups (group_id, title, is_active, created_at) VALUES (-1001, 'Legacy Group', 1, '2026-01-01T00:00:00+00:00')"
            )
            cur.execute(
                """
                INSERT INTO roles (role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
                VALUES (1, 'dev', 'd', 'sp', 'ei', NULL, 1)
                """
            )
            cur.execute(
                """
                INSERT INTO group_roles (
                    group_id, role_id, system_prompt_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
                )
                VALUES (-1001, 1, NULL, 'dev', NULL, NULL, NULL, 1, 'normal', 1)
                """
            )
            cur.execute(
                """
                INSERT INTO user_role_sessions (
                    telegram_user_id, role_id, group_id, session_id, created_at, last_used_at
                )
                VALUES (42, 1, -1001, 'sess-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
