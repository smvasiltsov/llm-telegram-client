from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC13AdditiveMigrationTests(unittest.TestCase):
    def test_stage1_additive_migration_backfills_team_role_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy_team.sqlite3"
            self._create_legacy_team_schema_without_team_role_id(db_path)

            storage = Storage(str(db_path))
            self.assertTrue(storage.has_team_role_surrogate_id())
            self.assertTrue(storage.has_session_team_role_id())
            self.assertTrue(storage.has_prepost_team_role_id())
            self.assertTrue(storage.has_skill_team_role_id())

            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                tr = conn.execute(
                    "SELECT team_role_id FROM team_roles WHERE team_id = 10 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(tr)
                team_role_id = int(tr["team_role_id"])
                self.assertGreater(team_role_id, 0)

                urs = conn.execute(
                    "SELECT team_role_id FROM user_role_sessions WHERE telegram_user_id = 42 AND team_id = 10 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(urs)
                self.assertEqual(int(urs["team_role_id"]), team_role_id)

                rpp = conn.execute(
                    "SELECT team_role_id FROM role_prepost_processing WHERE team_id = 10 AND role_id = 1 AND prepost_processing_id = 'echo'"
                ).fetchone()
                self.assertIsNotNone(rpp)
                self.assertEqual(int(rpp["team_role_id"]), team_role_id)

                rse = conn.execute(
                    "SELECT team_role_id FROM role_skills_enabled WHERE team_id = 10 AND role_id = 1 AND skill_id = 'echo.skill'"
                ).fetchone()
                self.assertIsNotNone(rse)
                self.assertEqual(int(rse["team_role_id"]), team_role_id)

                conn.execute(
                    """
                    INSERT INTO team_roles (
                        team_id, role_id, system_prompt_override, display_name, model_override,
                        user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
                    )
                    VALUES (10, 2, NULL, 'dev2', NULL, NULL, NULL, 1, 'normal', 1)
                    """
                )
                conn.commit()
                auto_assigned = conn.execute(
                    "SELECT team_role_id FROM team_roles WHERE team_id = 10 AND role_id = 2"
                ).fetchone()
                self.assertIsNotNone(auto_assigned)
                self.assertGreater(int(auto_assigned["team_role_id"]), team_role_id)

    def test_stage1_syncs_enabled_with_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy_team_sync.sqlite3"
            self._create_legacy_team_schema_without_team_role_id(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    UPDATE team_roles
                    SET enabled = 0, is_active = 1
                    WHERE team_id = 10 AND role_id = 1
                    """
                )
                conn.commit()

            _ = Storage(str(db_path))
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT enabled, is_active FROM team_roles WHERE team_id = 10 AND role_id = 1"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(int(row["is_active"]), 1)
                self.assertEqual(int(row["enabled"]), 1)

    def test_stage1_cleans_up_orphan_team_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "legacy_team_orphan.sqlite3"
            self._create_legacy_team_schema_without_team_role_id(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    INSERT INTO team_roles (
                        team_id, role_id, system_prompt_override, display_name, model_override,
                        user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
                    )
                    VALUES (10, 999, NULL, 'ghost', NULL, NULL, NULL, 0, 'normal', 0);

                    INSERT INTO user_role_sessions (
                        telegram_user_id, team_id, role_id, session_id, created_at, last_used_at
                    )
                    VALUES (42, 10, 999, 'sess-ghost', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');

                    INSERT INTO role_prepost_processing (
                        team_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                    )
                    VALUES (10, 999, 'ghost.pre', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');

                    INSERT INTO role_skills_enabled (
                        team_id, role_id, skill_id, enabled, config_json, created_at, updated_at
                    )
                    VALUES (10, 999, 'ghost.skill', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
                    """
                )
                conn.commit()

            _ = Storage(str(db_path))

            with sqlite3.connect(db_path) as conn:
                orphan_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM team_roles tr
                        LEFT JOIN roles r ON r.role_id = tr.role_id
                        WHERE r.role_id IS NULL
                        """
                    ).fetchone()[0]
                )
                self.assertEqual(orphan_count, 0)
                ghost_sessions = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM user_role_sessions WHERE team_id = 10 AND role_id = 999"
                    ).fetchone()[0]
                )
                self.assertEqual(ghost_sessions, 0)
                ghost_prepost = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM role_prepost_processing WHERE team_id = 10 AND role_id = 999"
                    ).fetchone()[0]
                )
                self.assertEqual(ghost_prepost, 0)
                ghost_skills = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM role_skills_enabled WHERE team_id = 10 AND role_id = 999"
                    ).fetchone()[0]
                )
                self.assertEqual(ghost_skills, 0)

    @staticmethod
    def _create_legacy_team_schema_without_team_role_id(db_path: Path) -> None:
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
                INSERT INTO roles (role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
                VALUES (2, 'dev2', 'd', 'sp', 'ei', NULL, 1)
                """
            )
            conn.execute(
                """
                INSERT INTO team_roles (
                    team_id, role_id, system_prompt_override, display_name, model_override,
                    user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
                )
                VALUES (10, 1, NULL, 'dev', NULL, NULL, NULL, 1, 'normal', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO user_role_sessions (
                    telegram_user_id, team_id, role_id, session_id, created_at, last_used_at
                )
                VALUES (42, 10, 1, 'sess-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO role_prepost_processing (
                    team_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                )
                VALUES (10, 1, 'echo', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO role_skills_enabled (
                    team_id, role_id, skill_id, enabled, config_json, created_at, updated_at
                )
                VALUES (10, 1, 'echo.skill', 1, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.commit()


if __name__ == "__main__":
    unittest.main()
