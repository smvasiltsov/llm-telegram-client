from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class TeamMigrationCleanupTests(unittest.TestCase):
    def test_cleanup_migration_converts_legacy_schema_to_team_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.sqlite3"
            self._create_legacy_schema_with_data(db_path)

            storage = Storage(str(db_path))
            # ensure connection initialized and migration applied
            self.assertIsNotNone(storage.get_team_by_binding(interface_type="telegram", external_id="-1001"))

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                # legacy tables are removed in cleanup migration
                self.assertFalse(self._has_table(conn, "groups"))
                self.assertFalse(self._has_table(conn, "group_roles"))

                # team-only tables exist
                self.assertTrue(self._has_table(conn, "teams"))
                self.assertTrue(self._has_table(conn, "team_bindings"))
                self.assertTrue(self._has_table(conn, "team_roles"))
                self.assertTrue(self._has_table(conn, "user_role_sessions"))

                # team-only columns for migrated tables
                self.assertTrue(self._has_column(conn, "user_role_sessions", "team_id"))
                self.assertFalse(self._has_column(conn, "user_role_sessions", "group_id"))
                self.assertTrue(self._has_column(conn, "role_prepost_processing", "team_id"))
                self.assertFalse(self._has_column(conn, "role_prepost_processing", "group_id"))
                self.assertTrue(self._has_column(conn, "role_skills_enabled", "team_id"))
                self.assertFalse(self._has_column(conn, "role_skills_enabled", "group_id"))

                team_binding = conn.execute(
                    "SELECT team_id FROM team_bindings WHERE interface_type='telegram' AND external_id='-1001'"
                ).fetchone()
                self.assertIsNotNone(team_binding)
                team_id = int(team_binding["team_id"])

                team_role = conn.execute(
                    "SELECT role_id FROM team_roles WHERE team_id = ? AND role_id = 1",
                    (team_id,),
                ).fetchone()
                self.assertIsNotNone(team_role)

                session = conn.execute(
                    "SELECT session_id FROM user_role_sessions WHERE telegram_user_id = 42 AND team_id = ? AND role_id = 1",
                    (team_id,),
                ).fetchone()
                self.assertIsNotNone(session)
                self.assertEqual(session["session_id"], "sess-1")

                prepost = conn.execute(
                    "SELECT prepost_processing_id FROM role_prepost_processing WHERE team_id = ? AND role_id = 1",
                    (team_id,),
                ).fetchone()
                self.assertIsNotNone(prepost)

                skill = conn.execute(
                    "SELECT skill_id FROM role_skills_enabled WHERE team_id = ? AND role_id = 1",
                    (team_id,),
                ).fetchone()
                self.assertIsNotNone(skill)

    @staticmethod
    def _has_table(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row[1] == column for row in rows)

    @staticmethod
    def _create_legacy_schema_with_data(db_path: Path) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_authorized INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE groups (
                    group_id INTEGER PRIMARY KEY,
                    team_id INTEGER,
                    title TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE roles (
                    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    base_system_prompt TEXT NOT NULL,
                    extra_instruction TEXT NOT NULL,
                    llm_model TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

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
                );

                CREATE TABLE user_role_sessions (
                    telegram_user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    team_id INTEGER,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, group_id, role_id)
                );

                CREATE TABLE role_prepost_processing (
                    group_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    prepost_processing_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, role_id, prepost_processing_id)
                );

                CREATE TABLE role_skills_enabled (
                    group_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    skill_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, role_id, skill_id)
                );
                """
            )

            conn.execute(
                "INSERT INTO users (telegram_user_id, username, is_authorized, created_at) VALUES (42, 'u', 1, '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                "INSERT INTO groups (group_id, team_id, title, is_active, created_at) VALUES (-1001, NULL, 'Legacy Group', 1, '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                """
                INSERT INTO roles (role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
                VALUES (1, 'analyst', 'd', 'p', 'i', NULL, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO group_roles (group_id, role_id, system_prompt_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active)
                VALUES (-1001, 1, 'sp', 'analyst', NULL, NULL, NULL, 1, 'normal', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO user_role_sessions (telegram_user_id, role_id, group_id, team_id, session_id, created_at, last_used_at)
                VALUES (42, 1, -1001, NULL, 'sess-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO role_prepost_processing (group_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at)
                VALUES (-1001, 1, 'echo', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO role_skills_enabled (group_id, role_id, skill_id, enabled, config_json, created_at, updated_at)
                VALUES (-1001, 1, 'echo.skill', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.commit()


if __name__ == "__main__":
    unittest.main()
