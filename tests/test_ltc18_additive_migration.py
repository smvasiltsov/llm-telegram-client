from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC18AdditiveMigrationTests(unittest.TestCase):
    def test_stage1_additive_migration_creates_runtime_status_and_lock_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy_ltc18.sqlite3"
            self._create_legacy_schema_without_ltc18_tables(db_path)

            storage = Storage(str(db_path))
            self.assertTrue(storage.has_team_role_runtime_status_table())
            self.assertTrue(storage.has_role_lock_groups_table())
            self.assertTrue(storage.has_role_lock_group_members_table())

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                team_role = conn.execute(
                    "SELECT team_role_id FROM team_roles WHERE team_id = 10 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(team_role)
                team_role_id = int(team_role["team_role_id"])
                self.assertGreater(team_role_id, 0)

                status_row = conn.execute(
                    """
                    SELECT status, status_version, preview_text, busy_request_id
                    FROM team_role_runtime_status
                    WHERE team_role_id = ?
                    """,
                    (team_role_id,),
                ).fetchone()
                self.assertIsNotNone(status_row)
                self.assertEqual(status_row["status"], "free")
                self.assertEqual(int(status_row["status_version"]), 1)
                self.assertIsNone(status_row["preview_text"])
                self.assertIsNone(status_row["busy_request_id"])

                self.assertTrue(self._has_table(conn, "role_lock_groups"))
                self.assertTrue(self._has_table(conn, "role_lock_group_members"))
                self.assertTrue(self._has_column(conn, "team_role_runtime_status", "lease_expires_at"))
                self.assertTrue(self._has_column(conn, "team_role_runtime_status", "free_release_requested_at"))
                self.assertTrue(self._has_column(conn, "team_role_runtime_status", "free_release_delay_until"))
                self.assertTrue(self._has_column(conn, "team_role_runtime_status", "free_release_reason_pending"))
                self.assertTrue(self._has_column(conn, "role_lock_groups", "name"))
                self.assertTrue(self._has_column(conn, "role_lock_group_members", "team_role_id"))

    def test_init_schema_handles_legacy_runtime_status_without_delay_column(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy_ltc20_index.sqlite3"
            self._create_legacy_schema_with_runtime_status_without_delay(db_path)

            storage = Storage(str(db_path))
            self.assertTrue(storage.has_team_role_runtime_status_table())

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                self.assertTrue(self._has_column(conn, "team_role_runtime_status", "free_release_delay_until"))
                self.assertTrue(self._has_index(conn, "idx_team_role_runtime_status_delay_until"))

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
    def _has_index(conn: sqlite3.Connection, index: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name = ?",
            (index,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _create_legacy_schema_without_ltc18_tables(db_path: Path) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_authorized INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE teams (
                    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT NOT NULL UNIQUE,
                    name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    ext_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE team_bindings (
                    team_id INTEGER NOT NULL,
                    interface_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    external_title TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (interface_type, external_id)
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

                CREATE TABLE team_roles (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    role_name TEXT,
                    system_prompt_override TEXT,
                    display_name TEXT,
                    model_override TEXT,
                    user_prompt_suffix TEXT,
                    user_reply_prefix TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'normal',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (team_id, role_id)
                );

                CREATE TABLE user_role_sessions (
                    telegram_user_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, team_id, role_id)
                );

                CREATE TABLE role_prepost_processing (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    prepost_processing_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, role_id, prepost_processing_id)
                );

                CREATE TABLE role_skills_enabled (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    skill_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, role_id, skill_id)
                );
                """
            )
            conn.execute(
                "INSERT INTO users (telegram_user_id, username, is_authorized, created_at) VALUES (42, 'u', 1, '2026-01-01T00:00:00+00:00')"
            )
            conn.execute(
                """
                INSERT INTO teams (team_id, public_id, name, is_active, ext_json, created_at, updated_at)
                VALUES (10, 'team-10', 'Team 10', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO roles (role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
                VALUES (1, 'dev', 'd', 'sp', 'ei', NULL, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO team_roles (
                    team_id, role_id, role_name, system_prompt_override, display_name, model_override,
                    user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
                )
                VALUES (10, 1, 'dev', NULL, 'dev', NULL, NULL, NULL, 1, 'normal', 1)
                """
            )
            conn.commit()

    @staticmethod
    def _create_legacy_schema_with_runtime_status_without_delay(db_path: Path) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_authorized INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE teams (
                    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT NOT NULL UNIQUE,
                    name TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    ext_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE team_roles (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    team_role_id INTEGER,
                    role_name TEXT,
                    system_prompt_override TEXT,
                    extra_instruction_override TEXT,
                    display_name TEXT,
                    model_override TEXT,
                    user_prompt_suffix TEXT,
                    user_reply_prefix TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'normal',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (team_id, role_id)
                );

                CREATE TABLE team_role_runtime_status (
                    team_role_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'free',
                    status_version INTEGER NOT NULL DEFAULT 1,
                    busy_request_id TEXT,
                    busy_owner_user_id INTEGER,
                    busy_origin TEXT,
                    preview_text TEXT,
                    preview_source TEXT,
                    busy_since TEXT,
                    lease_expires_at TEXT,
                    last_heartbeat_at TEXT,
                    last_release_reason TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()


if __name__ == "__main__":
    unittest.main()
