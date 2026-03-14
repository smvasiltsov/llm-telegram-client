from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC12AdditiveRoleNameMigrationTests(unittest.TestCase):
    def test_migration_adds_role_name_columns_and_backfills(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy.sqlite3"
            self._create_legacy_schema_without_role_name_bindings(db_path)

            storage = Storage(db_path)

            self.assertTrue(storage.has_team_role_name_binding())
            self.assertTrue(storage.has_provider_user_data_role_name())
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                team_role = conn.execute(
                    "SELECT role_name FROM team_roles WHERE team_id = 10 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(team_role)
                self.assertEqual(team_role["role_name"], "analyst")

                provider_data = conn.execute(
                    "SELECT role_name FROM provider_user_data WHERE provider_id = 'p' AND key = 'k' AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(provider_data)
                self.assertEqual(provider_data["role_name"], "analyst")

    @staticmethod
    def _create_legacy_schema_without_role_name_bindings(db_path: Path) -> None:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
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
            CREATE TABLE users (
                telegram_user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_authorized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE teams (
                team_id INTEGER PRIMARY KEY AUTOINCREMENT,
                public_id TEXT NOT NULL UNIQUE,
                name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                ext_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE team_roles (
                team_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                team_role_id INTEGER,
                system_prompt_override TEXT,
                display_name TEXT,
                model_override TEXT,
                user_prompt_suffix TEXT,
                user_reply_prefix TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                mode TEXT NOT NULL DEFAULT 'normal',
                is_active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (team_id, role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE provider_user_data (
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                role_id INTEGER,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, role_id)
            )
            """
        )
        cur.execute(
            """
            INSERT INTO roles (role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
            VALUES (1, 'analyst', 'd', 'sp', 'ei', NULL, 1)
            """
        )
        cur.execute(
            """
            INSERT INTO teams (team_id, public_id, name, is_active, ext_json, created_at, updated_at)
            VALUES (10, 'team-10', 'T', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        cur.execute(
            """
            INSERT INTO team_roles (
                team_id, role_id, team_role_id, system_prompt_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            )
            VALUES (10, 1, 100, NULL, NULL, NULL, NULL, NULL, 1, 'normal', 1)
            """
        )
        cur.execute(
            """
            INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
            VALUES ('p', 'k', 1, 'v', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
