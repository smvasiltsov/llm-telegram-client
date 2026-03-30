from __future__ import annotations

import secrets
import sqlite3
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.models import (
    AuthToken,
    Group,
    GroupRole,
    RoleLockGroup,
    Role,
    RolePrePostProcessing,
    RoleSkill,
    SkillRun,
    Team,
    TeamBinding,
    TeamRole,
    TeamRoleRuntimeStatus,
    User,
    UserRoleSession,
)

if TYPE_CHECKING:
    from app.role_catalog import RoleCatalog


@dataclass
class SessionResolution:
    role: Role
    session: UserRoleSession | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_plus_seconds(ts: str, seconds: int) -> str:
    return (datetime.fromisoformat(ts) + timedelta(seconds=max(0, int(seconds)))).isoformat()


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._role_catalog: RoleCatalog | None = None
        self._init_schema()

    def attach_role_catalog(self, role_catalog: "RoleCatalog") -> None:
        self._role_catalog = role_catalog

    def _table_has_column(self, table: str, column: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any(row["name"] == column for row in cur.fetchall())

    def _table_exists(self, table: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,))
        return cur.fetchone() is not None

    # LTC-13 safety-net helpers: allow runtime/migrations to branch safely by schema capability.
    def has_team_role_surrogate_id(self) -> bool:
        return self._table_has_column("team_roles", "team_role_id")

    def has_session_team_role_id(self) -> bool:
        return self._table_has_column("user_role_sessions", "team_role_id")

    def has_prepost_team_role_id(self) -> bool:
        return self._table_has_column("role_prepost_processing", "team_role_id")

    def has_skill_team_role_id(self) -> bool:
        return self._table_has_column("role_skills_enabled", "team_role_id")

    # LTC-12 safety-net helpers: schema feature-gates for JSON master-role migration.
    def has_team_role_name_binding(self) -> bool:
        return self._table_has_column("team_roles", "role_name")

    def has_provider_user_data_role_name(self) -> bool:
        return self._table_has_column("provider_user_data", "role_name")

    def has_provider_user_data_team_role_table(self) -> bool:
        return self._table_exists("provider_user_data_team_role")

    def has_provider_user_data_team_role_legacy_blocks_table(self) -> bool:
        return self._table_exists("provider_user_data_team_role_legacy_blocks")

    def has_legacy_roles_table(self) -> bool:
        return self._table_exists("roles")

    # LTC-18 safety-net helpers: runtime status and lock-group schema capability checks.
    def has_team_role_runtime_status_table(self) -> bool:
        return self._table_exists("team_role_runtime_status")

    def has_role_lock_groups_table(self) -> bool:
        return self._table_exists("role_lock_groups")

    def has_role_lock_group_members_table(self) -> bool:
        return self._table_exists("role_lock_group_members")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in cur.fetchall()}
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            self._conn.commit()

    def _create_index_if_column_exists(self, *, index_name: str, table: str, column: str) -> None:
        if not self._table_has_column(table, column):
            return
        cur = self._conn.cursor()
        cur.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})")

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
                username TEXT,
                is_authorized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS teams (
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
            CREATE TABLE IF NOT EXISTS team_bindings (
                team_id INTEGER NOT NULL,
                interface_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                external_title TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (interface_type, external_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS roles (
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
            CREATE TABLE IF NOT EXISTS user_role_sessions (
                telegram_user_id INTEGER NOT NULL,
                team_id INTEGER,
                role_id INTEGER NOT NULL,
                team_role_id INTEGER,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (telegram_user_id, team_id, role_id),
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                telegram_user_id INTEGER PRIMARY KEY,
                encrypted_token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_authorized INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_user_data (
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                role_id INTEGER,
                role_name TEXT,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_user_data_team_role (
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                team_role_id INTEGER NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, team_role_id),
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_user_data_team_role_legacy_blocks (
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                team_role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, team_role_id),
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS plugin_texts (
                text_id TEXT PRIMARY KEY,
                plugin_id TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                command_text TEXT NOT NULL,
                role TEXT,
                requires_password INTEGER NOT NULL DEFAULT 0,
                trusted INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                exit_code INTEGER,
                duration_ms INTEGER,
                error_text TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_prepost_processing (
                team_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                team_role_id INTEGER,
                prepost_processing_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, role_id, prepost_processing_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_skills_enabled (
                team_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                team_role_id INTEGER,
                skill_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, role_id, skill_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS team_roles (
                team_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                role_name TEXT,
                team_role_id INTEGER,
                system_prompt_override TEXT,
                extra_instruction_override TEXT,
                display_name TEXT,
                model_override TEXT,
                user_prompt_suffix TEXT,
                user_reply_prefix TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                mode TEXT NOT NULL DEFAULT 'normal',
                is_active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (team_id, role_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS skill_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                skill_id TEXT NOT NULL,
                arguments_json TEXT,
                config_json TEXT,
                status TEXT NOT NULL,
                ok INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER,
                error_text TEXT,
                output_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS team_role_runtime_status (
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
                free_release_requested_at TEXT,
                free_release_delay_until TEXT,
                free_release_reason_pending TEXT,
                last_release_reason TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id),
                CHECK (status IN ('free', 'busy'))
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_lock_groups (
                lock_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_lock_group_members (
                lock_group_id INTEGER NOT NULL,
                team_role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (lock_group_id, team_role_id),
                FOREIGN KEY (lock_group_id) REFERENCES role_lock_groups(lock_group_id),
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_skill_runs_chain_step ON skill_runs(chain_id, step_index, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_skill_runs_skill_created ON skill_runs(skill_id, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_role_runtime_status_status ON team_role_runtime_status(status)")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_provider_user_data_team_role_lookup
            ON provider_user_data_team_role(provider_id, key, team_role_id, updated_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_provider_user_data_team_role_legacy_blocks_lookup
            ON provider_user_data_team_role_legacy_blocks(provider_id, key, team_role_id)
            """
        )
        self._create_index_if_column_exists(
            index_name="idx_team_role_runtime_status_lease",
            table="team_role_runtime_status",
            column="lease_expires_at",
        )
        self._create_index_if_column_exists(
            index_name="idx_team_role_runtime_status_delay_until",
            table="team_role_runtime_status",
            column="free_release_delay_until",
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_role_lock_group_members_team_role ON role_lock_group_members(team_role_id)")
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_team_roles_unique_display_name
            ON team_roles(team_id, lower(display_name))
            WHERE is_active = 1 AND display_name IS NOT NULL AND display_name <> ''
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_bindings_team_iface ON team_bindings(team_id, interface_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_runs_user_created ON tool_runs(telegram_user_id, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_runs_tool_created ON tool_runs(tool_name, created_at)")
        self._conn.commit()

        # Backwards-compatible migrations for existing DBs
        self._ensure_column("users", "is_authorized", "is_authorized INTEGER NOT NULL DEFAULT 0")
        self._migrate_role_prepost_processing()
        self._migrate_to_team_only_schema()
        self._migrate_team_role_surrogate_additive()
        self._migrate_role_name_bindings_additive()
        self._migrate_provider_user_data_team_role_additive()
        self._migrate_role_runtime_status_additive()
        self._ensure_column("team_roles", "extra_instruction_override", "extra_instruction_override TEXT")
        self._conn.commit()

    def _migrate_provider_user_data_team_role_additive(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_user_data_team_role (
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                team_role_id INTEGER NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, team_role_id),
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_provider_user_data_team_role_lookup
            ON provider_user_data_team_role(provider_id, key, team_role_id, updated_at)
            """
        )
        # Best-effort backfill from legacy role-scoped storage to team-role scoped storage.
        # On conflict, keep the value with the most recent updated_at.
        cur.execute(
            """
            INSERT INTO provider_user_data_team_role (
                provider_id,
                key,
                team_role_id,
                value,
                created_at,
                updated_at
            )
            SELECT
                pud.provider_id,
                pud.key,
                tr.team_role_id,
                pud.value,
                pud.created_at,
                pud.updated_at
            FROM provider_user_data pud
            JOIN team_roles tr ON tr.role_id = pud.role_id
            WHERE pud.role_id IS NOT NULL
              AND tr.team_role_id IS NOT NULL
            ON CONFLICT(provider_id, key, team_role_id) DO UPDATE SET
                value = excluded.value,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            WHERE excluded.updated_at > provider_user_data_team_role.updated_at
            """
        )
        self._conn.commit()

    def _migrate_role_runtime_status_additive(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS team_role_runtime_status (
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
                free_release_requested_at TEXT,
                free_release_delay_until TEXT,
                free_release_reason_pending TEXT,
                last_release_reason TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id),
                CHECK (status IN ('free', 'busy'))
            )
            """
        )
        self._ensure_column("team_role_runtime_status", "free_release_requested_at", "free_release_requested_at TEXT")
        self._ensure_column("team_role_runtime_status", "free_release_delay_until", "free_release_delay_until TEXT")
        self._ensure_column("team_role_runtime_status", "free_release_reason_pending", "free_release_reason_pending TEXT")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_lock_groups (
                lock_group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS role_lock_group_members (
                lock_group_id INTEGER NOT NULL,
                team_role_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (lock_group_id, team_role_id),
                FOREIGN KEY (lock_group_id) REFERENCES role_lock_groups(lock_group_id),
                FOREIGN KEY (team_role_id) REFERENCES team_roles(team_role_id)
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_role_runtime_status_status ON team_role_runtime_status(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_role_runtime_status_lease ON team_role_runtime_status(lease_expires_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_team_role_runtime_status_delay_until ON team_role_runtime_status(free_release_delay_until)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_role_lock_group_members_team_role ON role_lock_group_members(team_role_id)")

        now = _utc_now()
        cur.execute(
            """
            INSERT OR IGNORE INTO team_role_runtime_status (
                team_role_id,
                status,
                status_version,
                updated_at
            )
            SELECT
                tr.team_role_id,
                'free',
                1,
                ?
            FROM team_roles tr
            WHERE tr.team_role_id IS NOT NULL AND tr.is_active = 1
            """,
            (now,),
        )
        self._conn.commit()

    def _migrate_role_name_bindings_additive(self) -> None:
        cur = self._conn.cursor()
        self._ensure_column("team_roles", "role_name", "role_name TEXT")
        self._ensure_column("provider_user_data", "role_name", "role_name TEXT")

        if self._table_exists("roles"):
            cur.execute(
                """
                UPDATE team_roles
                SET role_name = (
                    SELECT r.role_name
                    FROM roles r
                    WHERE r.role_id = team_roles.role_id
                    LIMIT 1
                )
                WHERE role_name IS NULL OR role_name = ''
                """
            )
            cur.execute(
                """
                UPDATE provider_user_data
                SET role_name = (
                    SELECT r.role_name
                    FROM roles r
                    WHERE r.role_id = provider_user_data.role_id
                    LIMIT 1
                )
                WHERE role_id IS NOT NULL AND (role_name IS NULL OR role_name = '')
                """
            )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_team_roles_team_role_name
            ON team_roles(team_id, role_name)
            WHERE role_name IS NOT NULL AND role_name <> ''
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_provider_user_data_role_name
            ON provider_user_data(provider_id, key, role_name)
            WHERE role_name IS NOT NULL AND role_name <> ''
            """
        )
        self._conn.commit()

    def _migrate_team_role_surrogate_additive(self) -> None:
        cur = self._conn.cursor()
        if not self._table_exists("team_roles"):
            return
        self._ensure_column("team_roles", "team_role_id", "team_role_id INTEGER")
        self._ensure_column("user_role_sessions", "team_role_id", "team_role_id INTEGER")
        self._ensure_column("role_prepost_processing", "team_role_id", "team_role_id INTEGER")
        self._ensure_column("role_skills_enabled", "team_role_id", "team_role_id INTEGER")

        cur.execute("SELECT COALESCE(MAX(team_role_id), 0) AS max_id FROM team_roles")
        row = cur.fetchone()
        next_id = int(row["max_id"] or 0) + 1
        cur.execute(
            """
            SELECT team_id, role_id
            FROM team_roles
            WHERE team_role_id IS NULL
            ORDER BY team_id, role_id
            """
        )
        for tr in cur.fetchall():
            cur.execute(
                """
                UPDATE team_roles
                SET team_role_id = ?
                WHERE team_id = ? AND role_id = ?
                """,
                (next_id, int(tr["team_id"]), int(tr["role_id"])),
            )
            next_id += 1

        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_team_roles_team_role_id
            ON team_roles(team_role_id)
            WHERE team_role_id IS NOT NULL
            """
        )
        cur.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_team_roles_assign_team_role_id
            AFTER INSERT ON team_roles
            FOR EACH ROW
            WHEN NEW.team_role_id IS NULL
            BEGIN
                UPDATE team_roles
                SET team_role_id = (
                    SELECT COALESCE(MAX(team_role_id), 0) + 1
                    FROM team_roles
                    WHERE NOT (team_id = NEW.team_id AND role_id = NEW.role_id)
                )
                WHERE team_id = NEW.team_id AND role_id = NEW.role_id;
            END
            """
        )

        cur.execute(
            """
            UPDATE user_role_sessions
            SET team_role_id = (
                SELECT tr.team_role_id
                FROM team_roles tr
                WHERE tr.team_id = user_role_sessions.team_id
                  AND tr.role_id = user_role_sessions.role_id
                LIMIT 1
            )
            WHERE team_role_id IS NULL AND team_id IS NOT NULL
            """
        )
        cur.execute(
            """
            UPDATE role_prepost_processing
            SET team_role_id = (
                SELECT tr.team_role_id
                FROM team_roles tr
                WHERE tr.team_id = role_prepost_processing.team_id
                  AND tr.role_id = role_prepost_processing.role_id
                LIMIT 1
            )
            WHERE team_role_id IS NULL
            """
        )
        cur.execute(
            """
            UPDATE role_skills_enabled
            SET team_role_id = (
                SELECT tr.team_role_id
                FROM team_roles tr
                WHERE tr.team_id = role_skills_enabled.team_id
                  AND tr.role_id = role_skills_enabled.role_id
                LIMIT 1
            )
            WHERE team_role_id IS NULL
            """
        )

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_role_sessions_team_role_id "
            "ON user_role_sessions(team_role_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_prepost_processing_team_role_id "
            "ON role_prepost_processing(team_role_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_skills_enabled_team_role_id "
            "ON role_skills_enabled(team_role_id)"
        )
        self._conn.commit()

    def _migrate_teams_additive(self) -> None:
        cur = self._conn.cursor()
        if not self._table_exists("groups"):
            return
        if self._table_has_column("groups", "team_id"):
            pass
        else:
            self._ensure_column("groups", "team_id", "team_id INTEGER")
        cur.execute(
            """
            SELECT group_id, team_id, title, is_active, created_at
            FROM groups
            ORDER BY group_id
            """
        )
        groups = cur.fetchall()
        now = _utc_now()
        for row in groups:
            group_id = int(row["group_id"])
            team_id = row["team_id"]
            title = row["title"]
            is_active = 1 if bool(row["is_active"]) else 0
            created_at = row["created_at"] or now
            if team_id is None:
                public_id = self._generate_team_public_id(group_id=group_id)
                cur.execute(
                    """
                    INSERT INTO teams (public_id, name, is_active, ext_json, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?)
                    """,
                    (public_id, title, is_active, created_at, now),
                )
                team_id = int(cur.lastrowid)
                cur.execute(
                    """
                    UPDATE groups
                    SET team_id = ?
                    WHERE group_id = ?
                    """,
                    (team_id, group_id),
                )
            else:
                cur.execute("SELECT 1 FROM teams WHERE team_id = ?", (team_id,))
                if cur.fetchone() is None:
                    public_id = self._generate_team_public_id(group_id=group_id)
                    cur.execute(
                        """
                        INSERT INTO teams (team_id, public_id, name, is_active, ext_json, created_at, updated_at)
                        VALUES (?, ?, ?, ?, NULL, ?, ?)
                        """,
                        (int(team_id), public_id, title, is_active, created_at, now),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE teams
                        SET is_active = ?, name = COALESCE(name, ?), updated_at = ?
                        WHERE team_id = ?
                        """,
                        (is_active, title, now, int(team_id)),
                    )
            cur.execute(
                """
                INSERT OR IGNORE INTO team_bindings (
                    team_id, interface_type, external_id, external_title, is_active, created_at, updated_at
                )
                VALUES (?, 'telegram', ?, ?, ?, ?, ?)
                """,
                (int(team_id), str(group_id), title, is_active, created_at, now),
            )
            cur.execute(
                """
                UPDATE team_bindings
                SET external_title = ?, is_active = ?, updated_at = ?
                WHERE interface_type = 'telegram' AND external_id = ?
                """,
                (title, is_active, now, str(group_id)),
            )

        if self._table_exists("group_roles"):
            cur.execute(
                """
                INSERT OR IGNORE INTO team_roles (
                    team_id,
                    role_id,
                    system_prompt_override,
                    extra_instruction_override,
                    display_name,
                    model_override,
                    user_prompt_suffix,
                    user_reply_prefix,
                    enabled,
                    mode,
                    is_active
                )
                SELECT
                    g.team_id,
                    gr.role_id,
                    gr.system_prompt_override,
                    NULL,
                    gr.display_name,
                    gr.model_override,
                    gr.user_prompt_suffix,
                    gr.user_reply_prefix,
                    gr.enabled,
                    gr.mode,
                    gr.is_active
                FROM group_roles gr
                JOIN groups g ON g.group_id = gr.group_id
                WHERE g.team_id IS NOT NULL
                """
            )
        if self._table_has_column("user_role_sessions", "group_id") and self._table_exists("groups"):
            self._ensure_column("user_role_sessions", "team_id", "team_id INTEGER")
            cur.execute(
                """
                UPDATE user_role_sessions
                SET team_id = (
                    SELECT g.team_id FROM groups g WHERE g.group_id = user_role_sessions.group_id
                )
                WHERE team_id IS NULL
                """
            )
        self._conn.commit()

    def _migrate_to_team_only_schema(self) -> None:
        cur = self._conn.cursor()
        self._migrate_teams_additive()

        # user_role_sessions: migrate any legacy (group-scoped) schema to team-scoped PK.
        cur.execute("PRAGMA table_info(user_role_sessions)")
        session_cols = {row["name"] for row in cur.fetchall()}
        if "group_id" in session_cols or "team_id" not in session_cols:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_role_sessions_v3 (
                    telegram_user_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, team_id, role_id),
                    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                    FOREIGN KEY (team_id) REFERENCES teams(team_id),
                    FOREIGN KEY (role_id) REFERENCES roles(role_id)
                )
                """
            )
            if "group_id" in session_cols:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO user_role_sessions_v3
                        (telegram_user_id, team_id, role_id, session_id, created_at, last_used_at)
                    SELECT
                        urs.telegram_user_id,
                        COALESCE(
                            urs.team_id,
                            (
                                SELECT tb.team_id
                                FROM team_bindings tb
                                WHERE tb.interface_type = 'telegram' AND tb.external_id = CAST(urs.group_id AS TEXT)
                                LIMIT 1
                            )
                        ) AS resolved_team_id,
                        urs.role_id,
                        urs.session_id,
                        urs.created_at,
                        urs.last_used_at
                    FROM user_role_sessions urs
                    WHERE COALESCE(
                        urs.team_id,
                        (
                            SELECT tb.team_id
                            FROM team_bindings tb
                            WHERE tb.interface_type = 'telegram' AND tb.external_id = CAST(urs.group_id AS TEXT)
                            LIMIT 1
                        )
                    ) IS NOT NULL
                    """
                )
            else:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO user_role_sessions_v3
                        (telegram_user_id, team_id, role_id, session_id, created_at, last_used_at)
                    SELECT telegram_user_id, team_id, role_id, session_id, created_at, last_used_at
                    FROM user_role_sessions
                    WHERE team_id IS NOT NULL
                    """
                )
            cur.execute("DROP TABLE user_role_sessions")
            cur.execute("ALTER TABLE user_role_sessions_v3 RENAME TO user_role_sessions")

        # role_prepost_processing: migrate group-keyed table to team-keyed.
        cur.execute("PRAGMA table_info(role_prepost_processing)")
        prepost_cols = {row["name"] for row in cur.fetchall()}
        if "group_id" in prepost_cols:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS role_prepost_processing_v3 (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    prepost_processing_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, role_id, prepost_processing_id),
                    FOREIGN KEY (team_id) REFERENCES teams(team_id),
                    FOREIGN KEY (role_id) REFERENCES roles(role_id)
                )
                """
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO role_prepost_processing_v3
                    (team_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at)
                SELECT
                    tb.team_id,
                    rpp.role_id,
                    rpp.prepost_processing_id,
                    rpp.enabled,
                    rpp.config_json,
                    rpp.created_at,
                    rpp.updated_at
                FROM role_prepost_processing rpp
                JOIN team_bindings tb
                    ON tb.interface_type = 'telegram' AND tb.external_id = CAST(rpp.group_id AS TEXT)
                """
            )
            cur.execute("DROP TABLE role_prepost_processing")
            cur.execute("ALTER TABLE role_prepost_processing_v3 RENAME TO role_prepost_processing")

        # role_skills_enabled: migrate group-keyed table to team-keyed.
        cur.execute("PRAGMA table_info(role_skills_enabled)")
        skill_cols = {row["name"] for row in cur.fetchall()}
        if "group_id" in skill_cols:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS role_skills_enabled_v3 (
                    team_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    skill_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    config_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (team_id, role_id, skill_id),
                    FOREIGN KEY (team_id) REFERENCES teams(team_id),
                    FOREIGN KEY (role_id) REFERENCES roles(role_id)
                )
                """
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO role_skills_enabled_v3
                    (team_id, role_id, skill_id, enabled, config_json, created_at, updated_at)
                SELECT
                    tb.team_id,
                    rse.role_id,
                    rse.skill_id,
                    rse.enabled,
                    rse.config_json,
                    rse.created_at,
                    rse.updated_at
                FROM role_skills_enabled rse
                JOIN team_bindings tb
                    ON tb.interface_type = 'telegram' AND tb.external_id = CAST(rse.group_id AS TEXT)
                """
            )
            cur.execute("DROP TABLE role_skills_enabled")
            cur.execute("ALTER TABLE role_skills_enabled_v3 RENAME TO role_skills_enabled")

        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_role_sessions_team_role "
            "ON user_role_sessions(telegram_user_id, team_id, role_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_prepost_processing_role "
            "ON role_prepost_processing(team_id, role_id, enabled)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_skills_enabled_role "
            "ON role_skills_enabled(team_id, role_id, enabled)"
        )

        # group_roles/groups are no longer domain entities.
        if self._table_exists("group_roles"):
            cur.execute("DROP TABLE group_roles")
        if self._table_exists("groups"):
            cur.execute("DROP TABLE groups")
        self._conn.commit()

    def _generate_team_public_id(self, group_id: int) -> str:
        base = f"team-tg-{group_id}"
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM teams WHERE public_id = ?", (base,))
        if cur.fetchone() is None:
            return base
        while True:
            candidate = f"{base}-{secrets.token_hex(4)}"
            cur.execute("SELECT 1 FROM teams WHERE public_id = ?", (candidate,))
            if cur.fetchone() is None:
                return candidate

    def _migrate_role_prepost_processing(self) -> None:
        cur = self._conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='role_skills'")
        if cur.fetchone() is None:
            pass
        else:
            cur.execute("PRAGMA table_info(role_prepost_processing)")
            target_cols = {row["name"] for row in cur.fetchall()}
            if "team_id" in target_cols:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO role_prepost_processing
                        (team_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at)
                    SELECT
                        tb.team_id,
                        rs.role_id,
                        rs.skill_id,
                        rs.enabled,
                        rs.config_json,
                        rs.created_at,
                        rs.updated_at
                    FROM role_skills rs
                    JOIN team_bindings tb
                        ON tb.interface_type = 'telegram' AND tb.external_id = CAST(rs.group_id AS TEXT)
                    """
                )
            else:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO role_prepost_processing
                        (group_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at)
                    SELECT group_id, role_id, skill_id, enabled, config_json, created_at, updated_at
                    FROM role_skills
                    """
                )

        id_renames = {
            "crud-skill": "crud-processing",
            "exec-skill": "exec-processing",
        }
        for old_id, new_id in id_renames.items():
            cur.execute(
                """
                UPDATE OR IGNORE role_prepost_processing
                SET prepost_processing_id = ?
                WHERE prepost_processing_id = ?
                """,
                (new_id, old_id),
            )
        self._conn.commit()

    def save_plugin_text(self, plugin_id: str, text: str) -> str:
        now = _utc_now()
        cur = self._conn.cursor()
        for _ in range(5):
            text_id = secrets.token_urlsafe(12)
            try:
                cur.execute(
                    """
                    INSERT INTO plugin_texts (text_id, plugin_id, text, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (text_id, plugin_id, text, now),
                )
                self._conn.commit()
                return text_id
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("Failed to generate unique text_id")

    def get_plugin_text(self, plugin_id: str, text_id: str) -> dict[str, str] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT text_id, plugin_id, text, created_at
            FROM plugin_texts
            WHERE plugin_id = ? AND text_id = ?
            """,
            (plugin_id, text_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "text_id": row["text_id"],
            "plugin_id": row["plugin_id"],
            "text": row["text"],
            "created_at": row["created_at"],
        }

    def log_tool_run(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        source: str,
        tool_name: str,
        command_text: str,
        role: str | None,
        requires_password: bool,
        trusted: bool,
        status: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        error_text: str | None = None,
    ) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO tool_runs (
                telegram_user_id,
                chat_id,
                source,
                tool_name,
                command_text,
                role,
                requires_password,
                trusted,
                status,
                exit_code,
                duration_ms,
                error_text,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                chat_id,
                source,
                tool_name,
                command_text,
                role,
                1 if requires_password else 0,
                1 if trusted else 0,
                status,
                exit_code,
                duration_ms,
                error_text,
                now,
            ),
        )
        self._conn.commit()

    def log_skill_run(
        self,
        *,
        chain_id: str,
        step_index: int,
        telegram_user_id: int,
        chat_id: int,
        role_id: int,
        skill_id: str,
        arguments: dict | None,
        config: dict | None,
        status: str,
        ok: bool,
        duration_ms: int | None = None,
        error_text: str | None = None,
        output: dict | None = None,
    ) -> SkillRun:
        now = _utc_now()
        arguments_json = json.dumps(arguments, ensure_ascii=False) if arguments is not None else None
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        output_json = json.dumps(output, ensure_ascii=False) if output is not None else None
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO skill_runs (
                chain_id,
                step_index,
                telegram_user_id,
                chat_id,
                role_id,
                skill_id,
                arguments_json,
                config_json,
                status,
                ok,
                duration_ms,
                error_text,
                output_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chain_id,
                step_index,
                telegram_user_id,
                chat_id,
                role_id,
                skill_id,
                arguments_json,
                config_json,
                status,
                1 if ok else 0,
                duration_ms,
                error_text,
                output_json,
                now,
            ),
        )
        self._conn.commit()
        row_id = int(cur.lastrowid)
        skill_run = self.get_skill_run(row_id)
        if skill_run is None:
            raise RuntimeError("Failed to persist skill run")
        return skill_run

    def upsert_user(self, telegram_user_id: int, username: str | None) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO users (telegram_user_id, username, is_authorized, created_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username=excluded.username
            """,
            (telegram_user_id, username, now),
        )
        self._conn.commit()

    def upsert_group(self, group_id: int, title: str | None) -> Group:
        self.upsert_telegram_team_binding(group_id, title, is_active=True)
        return self.get_group(group_id)

    def _resolve_group_team_id(self, group_id: int) -> int | None:
        return self.resolve_team_id_by_telegram_chat(group_id)

    def _ensure_group_team_link(self, group_id: int) -> int:
        team_id = self.resolve_team_id_by_telegram_chat(group_id)
        if team_id is not None:
            return team_id
        return self.upsert_telegram_team_binding(group_id, None, is_active=True)

    def resolve_team_id_by_group_id_legacy(self, group_id: int) -> int:
        team_id = self.resolve_team_id_by_telegram_chat(group_id)
        if team_id is not None:
            return team_id
        return self.upsert_telegram_team_binding(group_id, None, is_active=True)

    def resolve_group_id_by_team_id_legacy(self, team_id: int) -> int | None:
        return self.resolve_telegram_chat_id_by_team_id(team_id)

    def get_team(self, team_id: int) -> Team:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, public_id, name, is_active, ext_json, created_at, updated_at
            FROM teams
            WHERE team_id = ?
            """,
            (team_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Team not found: {team_id}")
        return Team(
            team_id=row["team_id"],
            public_id=row["public_id"],
            name=row["name"],
            is_active=bool(row["is_active"]),
            ext_json=row["ext_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_teams(self) -> list[Team]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, public_id, name, is_active, ext_json, created_at, updated_at
            FROM teams
            WHERE is_active = 1
            ORDER BY team_id
            """
        )
        rows = cur.fetchall()
        return [
            Team(
                team_id=row["team_id"],
                public_id=row["public_id"],
                name=row["name"],
                is_active=bool(row["is_active"]),
                ext_json=row["ext_json"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def upsert_team(self, *, name: str | None, public_id: str | None = None, is_active: bool = True, ext_json: str | None = None) -> Team:
        cur = self._conn.cursor()
        now = _utc_now()
        effective_public_id = (public_id or f"team-{secrets.token_hex(8)}").strip()
        if not effective_public_id:
            effective_public_id = f"team-{secrets.token_hex(8)}"
        cur.execute(
            """
            INSERT INTO teams (public_id, name, is_active, ext_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(public_id) DO UPDATE SET
                name=excluded.name,
                is_active=excluded.is_active,
                ext_json=excluded.ext_json,
                updated_at=excluded.updated_at
            """,
            (effective_public_id, name, 1 if is_active else 0, ext_json, now, now),
        )
        self._conn.commit()
        cur.execute("SELECT team_id FROM teams WHERE public_id = ?", (effective_public_id,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to upsert team")
        return self.get_team(int(row["team_id"]))

    def upsert_team_binding(
        self,
        *,
        team_id: int,
        interface_type: str,
        external_id: str,
        external_title: str | None,
        is_active: bool = True,
    ) -> TeamBinding:
        cur = self._conn.cursor()
        now = _utc_now()
        iface = str(interface_type).strip().lower()
        ext_id = str(external_id).strip()
        cur.execute(
            """
            INSERT INTO team_bindings (
                team_id, interface_type, external_id, external_title, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(interface_type, external_id) DO UPDATE SET
                team_id=excluded.team_id,
                external_title=excluded.external_title,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """,
            (team_id, iface, ext_id, external_title, 1 if is_active else 0, now, now),
        )
        self._conn.commit()
        return self.get_team_binding(interface_type=iface, external_id=ext_id)

    def list_team_bindings(self, *, interface_type: str, active_only: bool = True) -> list[TeamBinding]:
        cur = self._conn.cursor()
        iface = str(interface_type).strip().lower()
        if active_only:
            cur.execute(
                """
                SELECT team_id, interface_type, external_id, external_title, is_active, created_at, updated_at
                FROM team_bindings
                WHERE interface_type = ? AND is_active = 1
                ORDER BY external_id
                """,
                (iface,),
            )
        else:
            cur.execute(
                """
                SELECT team_id, interface_type, external_id, external_title, is_active, created_at, updated_at
                FROM team_bindings
                WHERE interface_type = ?
                ORDER BY external_id
                """,
                (iface,),
            )
        rows = cur.fetchall()
        return [
            TeamBinding(
                team_id=row["team_id"],
                interface_type=row["interface_type"],
                external_id=row["external_id"],
                external_title=row["external_title"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_team_binding(self, *, interface_type: str, external_id: str) -> TeamBinding:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, interface_type, external_id, external_title, is_active, created_at, updated_at
            FROM team_bindings
            WHERE interface_type = ? AND external_id = ?
            """,
            (str(interface_type).strip().lower(), str(external_id).strip()),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Team binding not found: {interface_type}:{external_id}")
        return TeamBinding(
            team_id=row["team_id"],
            interface_type=row["interface_type"],
            external_id=row["external_id"],
            external_title=row["external_title"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_team_by_binding(self, *, interface_type: str, external_id: str) -> Team | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT t.team_id
            FROM teams t
            JOIN team_bindings tb ON tb.team_id = t.team_id
            WHERE tb.interface_type = ? AND tb.external_id = ? AND tb.is_active = 1
            LIMIT 1
            """,
            (str(interface_type).strip().lower(), str(external_id).strip()),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self.get_team(int(row["team_id"]))

    def resolve_team_id_by_telegram_chat(self, chat_id: int) -> int | None:
        team = self.get_team_by_binding(interface_type="telegram", external_id=str(chat_id))
        if team is None:
            return None
        return team.team_id

    def resolve_telegram_chat_id_by_team_id(self, team_id: int) -> int | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT external_id
            FROM team_bindings
            WHERE team_id = ? AND interface_type = 'telegram' AND is_active = 1
            ORDER BY external_id
            LIMIT 1
            """,
            (team_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        try:
            return int(row["external_id"])
        except Exception:
            return None

    def upsert_telegram_team_binding(self, chat_id: int, title: str | None, *, is_active: bool = True) -> int:
        team = self.get_team_by_binding(interface_type="telegram", external_id=str(chat_id))
        if team is None:
            public_id = f"team-tg-{chat_id}"
            team = self.upsert_team(name=title, public_id=public_id, is_active=is_active, ext_json=None)
        else:
            team = self.upsert_team(
                name=title if title is not None else team.name,
                public_id=team.public_id,
                is_active=is_active,
                ext_json=team.ext_json,
            )
        self.upsert_team_binding(
            team_id=team.team_id,
            interface_type="telegram",
            external_id=str(chat_id),
            external_title=title,
            is_active=is_active,
        )
        return team.team_id

    def set_telegram_team_binding_active(self, chat_id: int, is_active: bool) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_bindings
            SET is_active = ?, updated_at = ?
            WHERE interface_type = 'telegram' AND external_id = ?
            """,
            (1 if is_active else 0, now, str(chat_id)),
        )
        self._conn.commit()

    def get_skill_run(self, run_id: int) -> SkillRun | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                run_id,
                chain_id,
                step_index,
                telegram_user_id,
                chat_id,
                role_id,
                skill_id,
                arguments_json,
                config_json,
                status,
                ok,
                duration_ms,
                error_text,
                output_json,
                created_at
            FROM skill_runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return SkillRun(
            run_id=row["run_id"],
            chain_id=row["chain_id"],
            step_index=row["step_index"],
            telegram_user_id=row["telegram_user_id"],
            chat_id=row["chat_id"],
            role_id=row["role_id"],
            skill_id=row["skill_id"],
            arguments_json=row["arguments_json"],
            config_json=row["config_json"],
            status=row["status"],
            ok=bool(row["ok"]),
            duration_ms=row["duration_ms"],
            error_text=row["error_text"],
            output_json=row["output_json"],
            created_at=row["created_at"],
        )

    def get_group(self, group_id: int) -> Group:
        try:
            binding = self.get_team_binding(interface_type="telegram", external_id=str(group_id))
        except ValueError as exc:
            raise ValueError(f"Group not found: {group_id}") from exc
        team = self.get_team(binding.team_id)
        return Group(
            group_id=group_id,
            team_id=team.team_id,
            title=binding.external_title or team.name,
            is_active=bool(binding.is_active and team.is_active),
            created_at=binding.created_at,
        )

    def list_groups(self) -> list[Group]:
        result: list[Group] = []
        for binding in self.list_team_bindings(interface_type="telegram", active_only=True):
            try:
                group_id = int(binding.external_id)
            except Exception:
                continue
            team = self.get_team(binding.team_id)
            result.append(
                Group(
                    group_id=group_id,
                    team_id=team.team_id,
                    title=binding.external_title or team.name,
                    is_active=bool(binding.is_active and team.is_active),
                    created_at=binding.created_at,
                )
            )
        result.sort(key=lambda item: item.group_id)
        return result

    def add_conversation_message(self, session_id: str, role: str, content: str) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO conversation_messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, now),
        )
        self._conn.commit()

    def list_conversation_messages(self, session_id: str, limit: int | None = None) -> list[tuple[str, str]]:
        cur = self._conn.cursor()
        if limit is None:
            cur.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY message_id ASC
                """,
                (session_id,),
            )
        else:
            cur.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY message_id DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
        rows = cur.fetchall()
        if limit is not None:
            rows = list(reversed(rows))
        return [(row["role"], row["content"]) for row in rows]

    def get_provider_user_value(self, provider_id: str, key: str, role_id: int | None) -> str | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT value
            FROM provider_user_data
            WHERE provider_id = ? AND key = ? AND role_id IS ?
            """,
            (provider_id, key, role_id),
        )
        row = cur.fetchone()
        return str(row["value"]) if row else None

    def get_provider_user_value_by_team_role(
        self,
        provider_id: str,
        key: str,
        team_role_id: int,
    ) -> str | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT value
            FROM provider_user_data_team_role
            WHERE provider_id = ? AND key = ? AND team_role_id = ?
            """,
            (provider_id, key, int(team_role_id)),
        )
        row = cur.fetchone()
        return str(row["value"]) if row else None

    def get_provider_user_value_by_team_role_or_role(
        self,
        provider_id: str,
        key: str,
        *,
        team_role_id: int | None,
        role_id: int | None,
    ) -> str | None:
        if team_role_id is not None:
            value = self.get_provider_user_value_by_team_role(provider_id, key, int(team_role_id))
            if value is not None:
                return value
            if self.is_provider_user_legacy_fallback_blocked(provider_id, key, int(team_role_id)):
                return None
        return self.get_provider_user_value(provider_id, key, role_id)

    def is_provider_user_legacy_fallback_blocked(
        self,
        provider_id: str,
        key: str,
        team_role_id: int,
    ) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM provider_user_data_team_role_legacy_blocks
            WHERE provider_id = ? AND key = ? AND team_role_id = ?
            LIMIT 1
            """,
            (provider_id, key, int(team_role_id)),
        )
        return cur.fetchone() is not None

    def block_provider_user_legacy_fallback(
        self,
        provider_id: str,
        key: str,
        team_role_id: int,
    ) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO provider_user_data_team_role_legacy_blocks (provider_id, key, team_role_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(provider_id, key, team_role_id) DO NOTHING
            """,
            (provider_id, key, int(team_role_id), now),
        )
        self._conn.commit()

    def unblock_provider_user_legacy_fallback(
        self,
        provider_id: str,
        key: str,
        team_role_id: int,
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM provider_user_data_team_role_legacy_blocks
            WHERE provider_id = ? AND key = ? AND team_role_id = ?
            """,
            (provider_id, key, int(team_role_id)),
        )
        self._conn.commit()

    def set_provider_user_value(self, provider_id: str, key: str, role_id: int | None, value: str) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO provider_user_data (provider_id, key, role_id, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id, key, role_id) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (provider_id, key, role_id, value, now, now),
        )
        self._conn.commit()

    def delete_provider_user_value(self, provider_id: str, key: str, role_id: int | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM provider_user_data
            WHERE provider_id = ? AND key = ? AND role_id IS ?
            """,
            (provider_id, key, role_id),
        )
        self._conn.commit()

    def set_provider_user_value_by_team_role(
        self,
        provider_id: str,
        key: str,
        team_role_id: int,
        value: str,
    ) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO provider_user_data_team_role (provider_id, key, team_role_id, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider_id, key, team_role_id) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (provider_id, key, int(team_role_id), value, now, now),
        )
        self._conn.commit()

    def delete_provider_user_value_by_team_role(self, provider_id: str, key: str, team_role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM provider_user_data_team_role
            WHERE provider_id = ? AND key = ? AND team_role_id = ?
            """,
            (provider_id, key, int(team_role_id)),
        )
        self._conn.commit()

    def delete_all_provider_user_values_by_team_role(self, team_role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM provider_user_data_team_role
            WHERE team_role_id = ?
            """,
            (int(team_role_id),),
        )
        self._conn.commit()

    def list_provider_user_legacy_keys_for_role(self, role_id: int) -> list[tuple[str, str]]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT provider_id, key
            FROM provider_user_data
            WHERE role_id = ?
            """,
            (int(role_id),),
        )
        return [(str(row["provider_id"]), str(row["key"])) for row in cur.fetchall()]

    def set_group_active(self, group_id: int, is_active: bool) -> None:
        self.set_telegram_team_binding_active(group_id, is_active)

    def set_user_authorized(self, telegram_user_id: int, is_authorized: bool) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE users SET is_authorized = ? WHERE telegram_user_id = ?",
            (1 if is_authorized else 0, telegram_user_id),
        )
        self._conn.commit()

    def get_user(self, telegram_user_id: int) -> User | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT telegram_user_id, username, is_authorized, created_at FROM users WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return User(
            telegram_user_id=row["telegram_user_id"],
            username=row["username"],
            is_authorized=bool(row["is_authorized"]),
            created_at=row["created_at"],
        )

    def upsert_auth_token(self, telegram_user_id: int, encrypted_token: str) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO auth_tokens (telegram_user_id, encrypted_token, created_at, updated_at, is_authorized)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                encrypted_token=excluded.encrypted_token,
                updated_at=excluded.updated_at,
                is_authorized=1
            """,
            (telegram_user_id, encrypted_token, now, now),
        )
        self._conn.commit()

    def get_auth_token(self, telegram_user_id: int) -> AuthToken | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT telegram_user_id, encrypted_token, created_at, updated_at, is_authorized
            FROM auth_tokens
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return AuthToken(
            telegram_user_id=row["telegram_user_id"],
            encrypted_token=row["encrypted_token"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_authorized=bool(row["is_authorized"]),
        )

    def reset_authorizations(self) -> None:
        cur = self._conn.cursor()
        cur.execute("UPDATE users SET is_authorized = 0")
        cur.execute("UPDATE auth_tokens SET is_authorized = 0")
        self._conn.commit()

    def upsert_role(
        self,
        role_name: str,
        description: str,
        base_system_prompt: str,
        extra_instruction: str,
        llm_model: str | None,
        is_active: bool,
    ) -> Role:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO roles (role_name, description, base_system_prompt, extra_instruction, llm_model, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(role_name) DO UPDATE SET
                description=excluded.description,
                base_system_prompt=excluded.base_system_prompt,
                extra_instruction=excluded.extra_instruction,
                llm_model=excluded.llm_model,
                is_active=excluded.is_active
            """,
            (role_name, description, base_system_prompt, extra_instruction, llm_model, 1 if is_active else 0),
        )
        self._conn.commit()
        return self.get_role_by_name(role_name)

    def role_exists(self, role_name: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM roles WHERE role_name = ?", (role_name,))
        return cur.fetchone() is not None

    def generate_internal_role_name(self, prefix: str = "role") -> str:
        while True:
            candidate = f"{prefix}_{secrets.token_hex(6)}"
            if not self.role_exists(candidate):
                return candidate

    def _apply_catalog_master_fields(self, role: Role) -> Role:
        if self._role_catalog is None:
            return role
        catalog_role = self._role_catalog.get(role.role_name)
        if catalog_role is None:
            return role
        return Role(
            role_id=role.role_id,
            role_name=role.role_name,
            description=catalog_role.description,
            base_system_prompt=catalog_role.base_system_prompt,
            extra_instruction=catalog_role.extra_instruction,
            llm_model=catalog_role.llm_model,
            is_active=bool(catalog_role.is_active),
            mention_name=role.mention_name,
        )

    @staticmethod
    def _role_from_row(
        row: sqlite3.Row,
        *,
        fallback_role_name: str | None = None,
        mention_name: str | None = None,
    ) -> Role:
        role_name = row["role_name"] if "role_name" in row.keys() and row["role_name"] else fallback_role_name
        if not role_name:
            raise ValueError("Role row has no role_name")
        return Role(
            role_id=row["role_id"],
            role_name=str(role_name),
            description=str(row["description"] if "description" in row.keys() and row["description"] is not None else ""),
            base_system_prompt=str(
                row["base_system_prompt"] if "base_system_prompt" in row.keys() and row["base_system_prompt"] is not None else ""
            ),
            extra_instruction=str(
                row["extra_instruction"] if "extra_instruction" in row.keys() and row["extra_instruction"] is not None else ""
            ),
            llm_model=row["llm_model"] if "llm_model" in row.keys() else None,
            is_active=bool(row["is_active"] if "is_active" in row.keys() else True),
            mention_name=mention_name if mention_name is not None else (row["mention_name"] if "mention_name" in row.keys() else None),
        )

    def get_role_by_name(self, role_name: str) -> Role:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active
            FROM roles
            WHERE role_name = ?
            """,
            (role_name,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Role not found: {role_name}")
        return self._apply_catalog_master_fields(self._role_from_row(row))

    def get_role_by_id(self, role_id: int) -> Role:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active
            FROM roles
            WHERE role_id = ?
            """,
            (role_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Role not found: {role_id}")
        return self._apply_catalog_master_fields(self._role_from_row(row))

    def list_active_roles(self) -> list[Role]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active
            FROM roles
            WHERE is_active = 1
            ORDER BY role_name
            """
        )
        rows = cur.fetchall()
        return [self._apply_catalog_master_fields(self._role_from_row(row)) for row in rows]

    def list_roles(self) -> list[Role]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active
            FROM roles
            ORDER BY role_name
            """
        )
        rows = cur.fetchall()
        return [self._apply_catalog_master_fields(self._role_from_row(row)) for row in rows]

    def _team_role_to_group_role(self, team_role: TeamRole, group_id: int) -> GroupRole:
        return GroupRole(
            group_id=group_id,
            role_id=team_role.role_id,
            system_prompt_override=team_role.system_prompt_override,
            display_name=team_role.display_name,
            model_override=team_role.model_override,
            user_prompt_suffix=team_role.user_prompt_suffix,
            user_reply_prefix=team_role.user_reply_prefix,
            enabled=team_role.enabled,
            mode=team_role.mode,
            is_active=team_role.is_active,
        )

    def _row_to_team_role(self, row: sqlite3.Row) -> TeamRole:
        return TeamRole(
            team_id=row["team_id"],
            role_id=row["role_id"],
            team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
            system_prompt_override=row["system_prompt_override"],
            extra_instruction_override=row["extra_instruction_override"] if "extra_instruction_override" in row.keys() else None,
            display_name=row["display_name"],
            model_override=row["model_override"],
            user_prompt_suffix=row["user_prompt_suffix"],
            user_reply_prefix=row["user_reply_prefix"],
            enabled=bool(row["enabled"]),
            mode=str(row["mode"] or "normal"),
            is_active=bool(row["is_active"]),
        )

    @staticmethod
    def _row_to_team_role_runtime_status(row: sqlite3.Row) -> TeamRoleRuntimeStatus:
        return TeamRoleRuntimeStatus(
            team_role_id=int(row["team_role_id"]),
            status=str(row["status"] or "free"),
            status_version=int(row["status_version"] or 1),
            busy_request_id=row["busy_request_id"],
            busy_owner_user_id=int(row["busy_owner_user_id"]) if row["busy_owner_user_id"] is not None else None,
            busy_origin=row["busy_origin"],
            preview_text=row["preview_text"],
            preview_source=row["preview_source"],
            busy_since=row["busy_since"],
            lease_expires_at=row["lease_expires_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            free_release_requested_at=row["free_release_requested_at"] if "free_release_requested_at" in row.keys() else None,
            free_release_delay_until=row["free_release_delay_until"] if "free_release_delay_until" in row.keys() else None,
            free_release_reason_pending=row["free_release_reason_pending"] if "free_release_reason_pending" in row.keys() else None,
            last_release_reason=row["last_release_reason"],
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_role_lock_group(row: sqlite3.Row) -> RoleLockGroup:
        return RoleLockGroup(
            lock_group_id=int(row["lock_group_id"]),
            name=str(row["name"]),
            description=row["description"],
            is_active=bool(row["is_active"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def resolve_team_role_id(self, team_id: int, role_id: int, *, ensure_exists: bool = False) -> int | None:
        if ensure_exists:
            self.ensure_team_role(team_id, role_id)
        cur = self._conn.cursor()
        if self.has_team_role_surrogate_id():
            cur.execute(
                "SELECT team_role_id FROM team_roles WHERE team_id = ? AND role_id = ?",
                (team_id, role_id),
            )
            row = cur.fetchone()
            if row and row["team_role_id"] is not None:
                return int(row["team_role_id"])
        cur.execute(
            "SELECT 1 FROM team_roles WHERE team_id = ? AND role_id = ?",
            (team_id, role_id),
        )
        if cur.fetchone() is None:
            return None
        return None

    def resolve_team_role_identity(self, team_role_id: int) -> tuple[int, int] | None:
        if not self.has_team_role_surrogate_id():
            return None
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id
            FROM team_roles
            WHERE team_role_id = ?
            LIMIT 1
            """,
            (team_role_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return int(row["team_id"]), int(row["role_id"])

    def ensure_team_role(self, team_id: int, role_id: int) -> TeamRole:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO team_roles (
                team_id,
                role_id,
                role_name,
                system_prompt_override,
                extra_instruction_override,
                display_name,
                model_override,
                user_prompt_suffix,
                user_reply_prefix,
                enabled,
                mode,
                is_active
            )
            VALUES (
                ?, ?, (SELECT role_name FROM roles WHERE role_id = ?), NULL, NULL, NULL, NULL, NULL, NULL, 1, 'normal', 1
            )
            ON CONFLICT(team_id, role_id) DO NOTHING
            """,
            (team_id, role_id, role_id),
        )
        self._conn.commit()
        return self.get_team_role(team_id, role_id)

    def bind_master_role_to_team(self, team_id: int, role_id: int) -> tuple[TeamRole, bool]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT is_active
            FROM team_roles
            WHERE team_id = ? AND role_id = ?
            LIMIT 1
            """,
            (team_id, role_id),
        )
        row = cur.fetchone()
        if row is None:
            team_role = self.ensure_team_role(team_id, role_id)
            return team_role, True
        if not bool(row["is_active"]):
            cur.execute(
                """
                UPDATE team_roles
                SET is_active = 1, enabled = 1
                WHERE team_id = ? AND role_id = ?
                """,
                (team_id, role_id),
            )
            self._conn.commit()
            return self.get_team_role(team_id, role_id), True
        return self.get_team_role(team_id, role_id), False

    def get_team_role(self, team_id: int, role_id: int) -> TeamRole:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id, team_role_id, system_prompt_override, extra_instruction_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            FROM team_roles
            WHERE team_id = ? AND role_id = ?
            """,
            (team_id, role_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
        return self._row_to_team_role(row)

    def get_team_role_by_id(self, team_role_id: int) -> TeamRole:
        if not self.has_team_role_surrogate_id():
            raise ValueError("team_role_id is not supported by current schema")
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id, team_role_id, system_prompt_override, extra_instruction_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            FROM team_roles
            WHERE team_role_id = ?
            LIMIT 1
            """,
            (team_role_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Team role not found: team_role_id={team_role_id}")
        return self._row_to_team_role(row)

    def list_team_roles(self, team_id: int) -> list[TeamRole]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id, team_role_id, system_prompt_override, extra_instruction_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            FROM team_roles
            WHERE team_id = ? AND is_active = 1
            ORDER BY role_id
            """,
            (team_id,),
        )
        rows = cur.fetchall()
        return [self._row_to_team_role(row) for row in rows]

    def list_enabled_roles_for_team(self, team_id: int) -> list[TeamRole]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id, team_role_id, system_prompt_override, extra_instruction_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            FROM team_roles
            WHERE team_id = ? AND is_active = 1 AND enabled = 1
            ORDER BY role_id
            """,
            (team_id,),
        )
        rows = cur.fetchall()
        return [self._row_to_team_role(row) for row in rows]

    def get_enabled_orchestrator_for_team(self, team_id: int) -> TeamRole | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_id, role_id, team_role_id, system_prompt_override, extra_instruction_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, enabled, mode, is_active
            FROM team_roles
            WHERE team_id = ? AND is_active = 1 AND enabled = 1 AND mode = 'orchestrator'
            ORDER BY role_id
            LIMIT 2
            """,
            (team_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(f"Multiple enabled orchestrators found for team_id={team_id}")
        return self._row_to_team_role(rows[0])

    def list_roles_for_team(self, team_id: int) -> list[Role]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                tr.role_id,
                COALESCE(NULLIF(tr.role_name, ''), r.role_name) AS role_name,
                r.description,
                r.base_system_prompt,
                r.extra_instruction,
                r.llm_model,
                COALESCE(r.is_active, 1) AS is_active,
                COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name) AS mention_name
            FROM team_roles tr
            LEFT JOIN roles r ON r.role_id = tr.role_id
            WHERE tr.team_id = ? AND tr.is_active = 1 AND tr.enabled = 1
            ORDER BY lower(COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name))
            """,
            (team_id,),
        )
        rows = cur.fetchall()
        roles: list[Role] = []
        for row in rows:
            raw_name = row["role_name"]
            if raw_name is None or str(raw_name).strip() == "":
                continue
            role = self._apply_catalog_master_fields(self._role_from_row(row))
            role.mention_name = row["mention_name"]
            if role.is_active:
                roles.append(role)
        return roles

    def list_team_role_bindings_for_role(self, role_id: int, *, active_only: bool = True) -> list[dict[str, object]]:
        cur = self._conn.cursor()
        if active_only:
            cur.execute(
                """
                SELECT
                    tr.team_id,
                    t.name AS team_name,
                    tr.display_name,
                    tr.enabled,
                    tr.mode,
                    (
                        SELECT tb.external_id
                        FROM team_bindings tb
                        WHERE tb.team_id = tr.team_id
                          AND tb.interface_type = 'telegram'
                          AND tb.is_active = 1
                        ORDER BY tb.external_id
                        LIMIT 1
                    ) AS telegram_group_id,
                    (
                        SELECT tb.external_title
                        FROM team_bindings tb
                        WHERE tb.team_id = tr.team_id
                          AND tb.interface_type = 'telegram'
                          AND tb.is_active = 1
                        ORDER BY tb.external_id
                        LIMIT 1
                    ) AS telegram_group_title
                FROM team_roles tr
                JOIN teams t ON t.team_id = tr.team_id
                WHERE tr.role_id = ? AND tr.is_active = 1
                ORDER BY tr.team_id
                """,
                (role_id,),
            )
        else:
            cur.execute(
                """
                SELECT
                    tr.team_id,
                    t.name AS team_name,
                    tr.display_name,
                    tr.enabled,
                    tr.mode,
                    (
                        SELECT tb.external_id
                        FROM team_bindings tb
                        WHERE tb.team_id = tr.team_id
                          AND tb.interface_type = 'telegram'
                          AND tb.is_active = 1
                        ORDER BY tb.external_id
                        LIMIT 1
                    ) AS telegram_group_id,
                    (
                        SELECT tb.external_title
                        FROM team_bindings tb
                        WHERE tb.team_id = tr.team_id
                          AND tb.interface_type = 'telegram'
                          AND tb.is_active = 1
                        ORDER BY tb.external_id
                        LIMIT 1
                    ) AS telegram_group_title
                FROM team_roles tr
                JOIN teams t ON t.team_id = tr.team_id
                WHERE tr.role_id = ?
                ORDER BY tr.team_id
                """,
                (role_id,),
            )
        rows = cur.fetchall()
        return [
            {
                "team_id": int(row["team_id"]),
                "team_name": row["team_name"],
                "display_name": row["display_name"],
                "enabled": bool(row["enabled"]),
                "mode": str(row["mode"] or "normal"),
                "telegram_group_id": row["telegram_group_id"],
                "telegram_group_title": row["telegram_group_title"],
            }
            for row in rows
        ]

    def ensure_team_role_runtime_status(self, team_role_id: int) -> TeamRoleRuntimeStatus:
        self.get_team_role_by_id(team_role_id)
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO team_role_runtime_status (
                team_role_id, status, status_version, updated_at
            )
            VALUES (?, 'free', 1, ?)
            """,
            (team_role_id, now),
        )
        self._conn.commit()
        status = self.get_team_role_runtime_status(team_role_id)
        if status is None:
            raise ValueError(f"Runtime status not found: team_role_id={team_role_id}")
        return status

    def get_team_role_runtime_status(self, team_role_id: int) -> TeamRoleRuntimeStatus | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                team_role_id, status, status_version, busy_request_id, busy_owner_user_id,
                busy_origin, preview_text, preview_source, busy_since, lease_expires_at,
                last_heartbeat_at, free_release_requested_at, free_release_delay_until, free_release_reason_pending,
                last_release_reason, updated_at
            FROM team_role_runtime_status
            WHERE team_role_id = ?
            LIMIT 1
            """,
            (team_role_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_team_role_runtime_status(row)

    def list_team_role_runtime_statuses(self, team_id: int, *, active_only: bool = True) -> list[TeamRoleRuntimeStatus]:
        cur = self._conn.cursor()
        if active_only:
            cur.execute(
                """
                SELECT
                    rs.team_role_id, rs.status, rs.status_version, rs.busy_request_id, rs.busy_owner_user_id,
                    rs.busy_origin, rs.preview_text, rs.preview_source, rs.busy_since, rs.lease_expires_at,
                    rs.last_heartbeat_at, rs.free_release_requested_at, rs.free_release_delay_until,
                    rs.free_release_reason_pending, rs.last_release_reason, rs.updated_at
                FROM team_role_runtime_status rs
                JOIN team_roles tr ON tr.team_role_id = rs.team_role_id
                WHERE tr.team_id = ? AND tr.is_active = 1
                ORDER BY tr.role_id
                """,
                (team_id,),
            )
        else:
            cur.execute(
                """
                SELECT
                    rs.team_role_id, rs.status, rs.status_version, rs.busy_request_id, rs.busy_owner_user_id,
                    rs.busy_origin, rs.preview_text, rs.preview_source, rs.busy_since, rs.lease_expires_at,
                    rs.last_heartbeat_at, rs.free_release_requested_at, rs.free_release_delay_until,
                    rs.free_release_reason_pending, rs.last_release_reason, rs.updated_at
                FROM team_role_runtime_status rs
                JOIN team_roles tr ON tr.team_role_id = rs.team_role_id
                WHERE tr.team_id = ?
                ORDER BY tr.role_id
                """,
                (team_id,),
            )
        return [self._row_to_team_role_runtime_status(row) for row in cur.fetchall()]

    def update_team_role_runtime_preview(
        self,
        team_role_id: int,
        *,
        preview_text: str | None,
        preview_source: str | None,
        now: str | None = None,
    ) -> None:
        self.ensure_team_role_runtime_status(team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET preview_text = ?, preview_source = ?, updated_at = ?
            WHERE team_role_id = ?
            """,
            (preview_text, preview_source, now or _utc_now(), team_role_id),
        )
        self._conn.commit()

    def mark_team_role_runtime_busy(
        self,
        team_role_id: int,
        *,
        busy_request_id: str,
        busy_owner_user_id: int | None,
        busy_origin: str | None,
        preview_text: str | None,
        preview_source: str | None,
        busy_since: str,
        lease_expires_at: str | None,
        now: str | None = None,
    ) -> TeamRoleRuntimeStatus:
        self.ensure_team_role_runtime_status(team_role_id)
        ts = now or _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET
                status = 'busy',
                status_version = status_version + 1,
                busy_request_id = ?,
                busy_owner_user_id = ?,
                busy_origin = ?,
                preview_text = ?,
                preview_source = ?,
                busy_since = ?,
                lease_expires_at = ?,
                last_heartbeat_at = ?,
                free_release_requested_at = NULL,
                free_release_delay_until = NULL,
                free_release_reason_pending = NULL,
                updated_at = ?
            WHERE team_role_id = ?
            """,
            (
                busy_request_id,
                busy_owner_user_id,
                busy_origin,
                preview_text,
                preview_source,
                busy_since,
                lease_expires_at,
                busy_since,
                ts,
                team_role_id,
            ),
        )
        self._conn.commit()
        status = self.get_team_role_runtime_status(team_role_id)
        if status is None:
            raise ValueError(f"Runtime status not found: team_role_id={team_role_id}")
        return status

    def mark_team_role_runtime_free(
        self,
        team_role_id: int,
        *,
        release_reason: str | None,
        now: str | None = None,
    ) -> TeamRoleRuntimeStatus:
        self.ensure_team_role_runtime_status(team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET
                status = 'free',
                status_version = status_version + 1,
                busy_request_id = NULL,
                busy_owner_user_id = NULL,
                busy_origin = NULL,
                preview_text = NULL,
                preview_source = NULL,
                busy_since = NULL,
                lease_expires_at = NULL,
                last_heartbeat_at = ?,
                free_release_requested_at = NULL,
                free_release_delay_until = NULL,
                free_release_reason_pending = NULL,
                last_release_reason = ?,
                updated_at = ?
            WHERE team_role_id = ?
            """,
            (now or _utc_now(), release_reason, now or _utc_now(), team_role_id),
        )
        self._conn.commit()
        status = self.get_team_role_runtime_status(team_role_id)
        if status is None:
            raise ValueError(f"Runtime status not found: team_role_id={team_role_id}")
        return status

    def mark_team_role_runtime_release_requested(
        self,
        team_role_id: int,
        *,
        release_reason: str | None,
        requested_at: str,
        delay_until: str,
    ) -> TeamRoleRuntimeStatus:
        self.ensure_team_role_runtime_status(team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET
                status = 'busy',
                status_version = status_version + 1,
                free_release_requested_at = ?,
                free_release_delay_until = ?,
                free_release_reason_pending = ?,
                updated_at = ?
            WHERE team_role_id = ? AND status = 'busy'
            """,
            (requested_at, delay_until, release_reason, requested_at, team_role_id),
        )
        self._conn.commit()
        status = self.get_team_role_runtime_status(team_role_id)
        if status is None:
            raise ValueError(f"Runtime status not found: team_role_id={team_role_id}")
        return status

    def finalize_due_team_role_runtime_releases(self, *, now: str | None = None, limit: int = 100) -> int:
        ts = now or _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET
                status = 'free',
                status_version = status_version + 1,
                busy_request_id = NULL,
                busy_owner_user_id = NULL,
                busy_origin = NULL,
                preview_text = NULL,
                preview_source = NULL,
                busy_since = NULL,
                lease_expires_at = NULL,
                last_heartbeat_at = ?,
                last_release_reason = COALESCE(free_release_reason_pending, 'delayed_release'),
                free_release_requested_at = NULL,
                free_release_delay_until = NULL,
                free_release_reason_pending = NULL,
                updated_at = ?
            WHERE team_role_id IN (
                SELECT team_role_id
                FROM team_role_runtime_status
                WHERE status = 'busy'
                  AND free_release_delay_until IS NOT NULL
                  AND free_release_delay_until <= ?
                ORDER BY free_release_delay_until, team_role_id
                LIMIT ?
            )
            """,
            (ts, ts, ts, limit),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def list_due_team_role_runtime_releases(
        self,
        *,
        now: str | None = None,
        limit: int = 100,
    ) -> list[TeamRoleRuntimeStatus]:
        ts = now or _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                team_role_id, status, status_version, busy_request_id, busy_owner_user_id,
                busy_origin, preview_text, preview_source, busy_since, lease_expires_at,
                last_heartbeat_at, free_release_requested_at, free_release_delay_until, free_release_reason_pending,
                last_release_reason, updated_at
            FROM team_role_runtime_status
            WHERE status = 'busy'
              AND free_release_delay_until IS NOT NULL
              AND free_release_delay_until <= ?
            ORDER BY free_release_delay_until, team_role_id
            LIMIT ?
            """,
            (ts, limit),
        )
        return [self._row_to_team_role_runtime_status(row) for row in cur.fetchall()]

    def heartbeat_team_role_runtime_status(
        self,
        team_role_id: int,
        *,
        lease_expires_at: str | None,
        now: str | None = None,
    ) -> None:
        self.ensure_team_role_runtime_status(team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_role_runtime_status
            SET
                last_heartbeat_at = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE team_role_id = ? AND status = 'busy'
            """,
            (now or _utc_now(), lease_expires_at, now or _utc_now(), team_role_id),
        )
        self._conn.commit()

    def create_role_lock_group(self, name: str, description: str | None = None, *, is_active: bool = True) -> RoleLockGroup:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO role_lock_groups (name, description, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (name, description, 1 if is_active else 0, now, now),
        )
        self._conn.commit()
        group = self.get_role_lock_group_by_name(name)
        if group is None:
            raise ValueError(f"Lock group not found after upsert: name={name}")
        return group

    def get_role_lock_group_by_name(self, name: str) -> RoleLockGroup | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT lock_group_id, name, description, is_active, created_at, updated_at
            FROM role_lock_groups
            WHERE name = ?
            LIMIT 1
            """,
            (name,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_role_lock_group(row)

    def get_role_lock_group(self, lock_group_id: int) -> RoleLockGroup | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT lock_group_id, name, description, is_active, created_at, updated_at
            FROM role_lock_groups
            WHERE lock_group_id = ?
            LIMIT 1
            """,
            (lock_group_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_role_lock_group(row)

    def list_role_lock_groups(self, *, active_only: bool = True) -> list[RoleLockGroup]:
        cur = self._conn.cursor()
        if active_only:
            cur.execute(
                """
                SELECT lock_group_id, name, description, is_active, created_at, updated_at
                FROM role_lock_groups
                WHERE is_active = 1
                ORDER BY name
                """
            )
        else:
            cur.execute(
                """
                SELECT lock_group_id, name, description, is_active, created_at, updated_at
                FROM role_lock_groups
                ORDER BY name
                """
            )
        return [self._row_to_role_lock_group(row) for row in cur.fetchall()]

    def set_role_lock_group_active(self, lock_group_id: int, is_active: bool) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE role_lock_groups
            SET is_active = ?, updated_at = ?
            WHERE lock_group_id = ?
            """,
            (1 if is_active else 0, _utc_now(), lock_group_id),
        )
        self._conn.commit()

    def add_team_role_to_lock_group(self, lock_group_id: int, team_role_id: int) -> None:
        if self.get_role_lock_group(lock_group_id) is None:
            raise ValueError(f"Lock group not found: lock_group_id={lock_group_id}")
        self.get_team_role_by_id(team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO role_lock_group_members (lock_group_id, team_role_id, created_at)
            VALUES (?, ?, ?)
            """,
            (lock_group_id, team_role_id, _utc_now()),
        )
        self._conn.commit()

    def remove_team_role_from_lock_group(self, lock_group_id: int, team_role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM role_lock_group_members
            WHERE lock_group_id = ? AND team_role_id = ?
            """,
            (lock_group_id, team_role_id),
        )
        self._conn.commit()

    def list_lock_group_member_team_role_ids(self, lock_group_id: int) -> list[int]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT team_role_id
            FROM role_lock_group_members
            WHERE lock_group_id = ?
            ORDER BY team_role_id
            """,
            (lock_group_id,),
        )
        return [int(row["team_role_id"]) for row in cur.fetchall()]

    def list_lock_groups_for_team_role(self, team_role_id: int, *, active_only: bool = True) -> list[RoleLockGroup]:
        cur = self._conn.cursor()
        if active_only:
            cur.execute(
                """
                SELECT g.lock_group_id, g.name, g.description, g.is_active, g.created_at, g.updated_at
                FROM role_lock_groups g
                JOIN role_lock_group_members m ON m.lock_group_id = g.lock_group_id
                WHERE m.team_role_id = ? AND g.is_active = 1
                ORDER BY g.name
                """,
                (team_role_id,),
            )
        else:
            cur.execute(
                """
                SELECT g.lock_group_id, g.name, g.description, g.is_active, g.created_at, g.updated_at
                FROM role_lock_groups g
                JOIN role_lock_group_members m ON m.lock_group_id = g.lock_group_id
                WHERE m.team_role_id = ?
                ORDER BY g.name
                """,
                (team_role_id,),
            )
        return [self._row_to_role_lock_group(row) for row in cur.fetchall()]

    def list_related_lock_member_team_role_ids(self, team_role_id: int) -> list[int]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT m2.team_role_id
            FROM role_lock_group_members m1
            JOIN role_lock_groups g ON g.lock_group_id = m1.lock_group_id
            JOIN role_lock_group_members m2 ON m2.lock_group_id = m1.lock_group_id
            WHERE m1.team_role_id = ? AND g.is_active = 1
            ORDER BY m2.team_role_id
            """,
            (team_role_id,),
        )
        ids = {int(row["team_role_id"]) for row in cur.fetchall()}
        ids.add(int(team_role_id))
        return sorted(ids)

    def cleanup_stale_busy_team_roles(self, *, now: str | None = None, free_transition_delay_sec: int = 0) -> int:
        ts = now or _utc_now()
        delay_sec = max(0, int(free_transition_delay_sec))
        delay_until = _iso_plus_seconds(ts, delay_sec) if delay_sec > 0 else ts
        cur = self._conn.cursor()
        if delay_sec > 0:
            cur.execute(
                """
                UPDATE team_role_runtime_status
                SET
                    status_version = status_version + 1,
                    free_release_requested_at = COALESCE(free_release_requested_at, ?),
                    free_release_delay_until = COALESCE(free_release_delay_until, ?),
                    free_release_reason_pending = COALESCE(free_release_reason_pending, 'lease_expired_cleanup'),
                    updated_at = ?
                WHERE status = 'busy'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (ts, delay_until, ts, ts),
            )
        else:
            cur.execute(
                """
                UPDATE team_role_runtime_status
                SET
                    status = 'free',
                    status_version = status_version + 1,
                    busy_request_id = NULL,
                    busy_owner_user_id = NULL,
                    busy_origin = NULL,
                    preview_text = NULL,
                    preview_source = NULL,
                    busy_since = NULL,
                    lease_expires_at = NULL,
                    free_release_requested_at = NULL,
                    free_release_delay_until = NULL,
                    free_release_reason_pending = NULL,
                    last_release_reason = 'lease_expired_cleanup',
                    updated_at = ?
                WHERE status = 'busy'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (ts, ts),
            )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def try_acquire_team_role_busy(
        self,
        team_role_id: int,
        *,
        busy_request_id: str,
        busy_owner_user_id: int | None,
        busy_origin: str | None,
        preview_text: str | None,
        preview_source: str | None,
        busy_since: str,
        lease_expires_at: str | None,
        free_transition_delay_sec: int = 0,
        now: str | None = None,
    ) -> tuple[bool, TeamRoleRuntimeStatus | None, list[TeamRoleRuntimeStatus]]:
        self.get_team_role_by_id(team_role_id)
        ts = now or _utc_now()
        delay_sec = max(0, int(free_transition_delay_sec))
        delay_until = _iso_plus_seconds(ts, delay_sec) if delay_sec > 0 else ts
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                """
                INSERT OR IGNORE INTO team_role_runtime_status (
                    team_role_id, status, status_version, updated_at
                )
                VALUES (?, 'free', 1, ?)
                """,
                (team_role_id, ts),
            )
            if delay_sec > 0:
                cur.execute(
                    """
                    UPDATE team_role_runtime_status
                    SET
                        status_version = status_version + 1,
                        free_release_requested_at = COALESCE(free_release_requested_at, ?),
                        free_release_delay_until = COALESCE(free_release_delay_until, ?),
                        free_release_reason_pending = COALESCE(free_release_reason_pending, 'lease_expired_cleanup'),
                        updated_at = ?
                    WHERE status = 'busy'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                    """,
                    (ts, delay_until, ts, ts),
                )
            else:
                cur.execute(
                    """
                    UPDATE team_role_runtime_status
                    SET
                        status = 'free',
                        status_version = status_version + 1,
                        busy_request_id = NULL,
                        busy_owner_user_id = NULL,
                        busy_origin = NULL,
                        preview_text = NULL,
                        preview_source = NULL,
                        busy_since = NULL,
                        lease_expires_at = NULL,
                        free_release_requested_at = NULL,
                        free_release_delay_until = NULL,
                        free_release_reason_pending = NULL,
                        last_release_reason = 'lease_expired_cleanup',
                        updated_at = ?
                    WHERE status = 'busy'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                    """,
                    (ts, ts),
                )

            cur.execute(
                """
                UPDATE team_role_runtime_status
                SET
                    status = 'free',
                    status_version = status_version + 1,
                    busy_request_id = NULL,
                    busy_owner_user_id = NULL,
                    busy_origin = NULL,
                    preview_text = NULL,
                    preview_source = NULL,
                    busy_since = NULL,
                    lease_expires_at = NULL,
                    last_heartbeat_at = ?,
                    last_release_reason = COALESCE(free_release_reason_pending, 'delayed_release'),
                    free_release_requested_at = NULL,
                    free_release_delay_until = NULL,
                    free_release_reason_pending = NULL,
                    updated_at = ?
                WHERE status = 'busy'
                  AND free_release_delay_until IS NOT NULL
                  AND free_release_delay_until <= ?
                """,
                (ts, ts, ts),
            )

            related_ids = self.list_related_lock_member_team_role_ids(team_role_id)
            placeholders = ",".join("?" for _ in related_ids)
            cur.execute(
                f"""
                SELECT
                    team_role_id, status, status_version, busy_request_id, busy_owner_user_id,
                    busy_origin, preview_text, preview_source, busy_since, lease_expires_at,
                    last_heartbeat_at, free_release_requested_at, free_release_delay_until, free_release_reason_pending,
                    last_release_reason, updated_at
                FROM team_role_runtime_status
                WHERE team_role_id IN ({placeholders}) AND status = 'busy'
                ORDER BY team_role_id
                """,
                tuple(related_ids),
            )
            blockers = [self._row_to_team_role_runtime_status(row) for row in cur.fetchall()]
            external_blockers = [
                item for item in blockers if not (item.team_role_id == team_role_id and item.busy_request_id == busy_request_id)
            ]
            if external_blockers:
                self._conn.commit()
                return False, None, external_blockers

            cur.execute(
                """
                UPDATE team_role_runtime_status
                SET
                    status = 'busy',
                    status_version = status_version + 1,
                    busy_request_id = ?,
                    busy_owner_user_id = ?,
                    busy_origin = ?,
                    preview_text = ?,
                    preview_source = ?,
                    busy_since = ?,
                    lease_expires_at = ?,
                    last_heartbeat_at = ?,
                    free_release_requested_at = NULL,
                    free_release_delay_until = NULL,
                    free_release_reason_pending = NULL,
                    updated_at = ?
                WHERE team_role_id = ?
                """,
                (
                    busy_request_id,
                    busy_owner_user_id,
                    busy_origin,
                    preview_text,
                    preview_source,
                    busy_since,
                    lease_expires_at,
                    busy_since,
                    ts,
                    team_role_id,
                ),
            )
            cur.execute(
                """
                SELECT
                    team_role_id, status, status_version, busy_request_id, busy_owner_user_id,
                    busy_origin, preview_text, preview_source, busy_since, lease_expires_at,
                    last_heartbeat_at, free_release_requested_at, free_release_delay_until, free_release_reason_pending,
                    last_release_reason, updated_at
                FROM team_role_runtime_status
                WHERE team_role_id = ?
                LIMIT 1
                """,
                (team_role_id,),
            )
            row = cur.fetchone()
            self._conn.commit()
            if not row:
                return False, None, []
            return True, self._row_to_team_role_runtime_status(row), []
        except Exception:
            self._conn.rollback()
            raise

    def get_team_role_name(self, team_id: int, role_id: int) -> str:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name) AS name
            FROM team_roles tr
            LEFT JOIN roles r ON r.role_id = tr.role_id
            WHERE tr.team_id = ? AND tr.role_id = ?
            """,
            (team_id, role_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
        return str(row["name"])

    def get_role_for_team_by_name(self, team_id: int, role_name: str) -> Role:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                tr.role_id,
                COALESCE(NULLIF(tr.role_name, ''), r.role_name) AS role_name,
                r.description,
                r.base_system_prompt,
                r.extra_instruction,
                r.llm_model,
                COALESCE(r.is_active, 1) AS is_active,
                COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name) AS mention_name
            FROM team_roles tr
            LEFT JOIN roles r ON tr.role_id = r.role_id
            WHERE tr.team_id = ?
              AND tr.is_active = 1
              AND lower(COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name)) = lower(?)
            LIMIT 1
            """,
            (team_id, role_name),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Role not found in team: team_id={team_id} role_name={role_name}")
        role = self._apply_catalog_master_fields(self._role_from_row(row))
        role.mention_name = row["mention_name"]
        return role

    def team_role_name_exists(self, team_id: int, role_name: str, exclude_role_id: int | None = None) -> bool:
        cur = self._conn.cursor()
        if exclude_role_id is None:
            cur.execute(
                """
                SELECT 1
                FROM team_roles tr
                LEFT JOIN roles r ON r.role_id = tr.role_id
                WHERE tr.team_id = ?
                  AND tr.is_active = 1
                  AND lower(COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name)) = lower(?)
                LIMIT 1
                """,
                (team_id, role_name),
            )
        else:
            cur.execute(
                """
                SELECT 1
                FROM team_roles tr
                LEFT JOIN roles r ON r.role_id = tr.role_id
                WHERE tr.team_id = ?
                  AND tr.is_active = 1
                  AND tr.role_id != ?
                  AND lower(COALESCE(NULLIF(tr.display_name, ''), NULLIF(tr.role_name, ''), r.role_name)) = lower(?)
                LIMIT 1
                """,
                (team_id, exclude_role_id, role_name),
            )
        return cur.fetchone() is not None

    def set_team_role_prompt(self, team_id: int, role_id: int, system_prompt_override: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET system_prompt_override = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (system_prompt_override, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_display_name(self, team_id: int, role_id: int, display_name: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET display_name = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (display_name, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_model(self, team_id: int, role_id: int, model_override: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET model_override = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (model_override, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_extra_instruction(self, team_id: int, role_id: int, extra_instruction_override: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET extra_instruction_override = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (extra_instruction_override, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_user_prompt_suffix(self, team_id: int, role_id: int, user_prompt_suffix: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET user_prompt_suffix = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (user_prompt_suffix, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_user_reply_prefix(self, team_id: int, role_id: int, user_reply_prefix: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET user_reply_prefix = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (user_reply_prefix, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_enabled(self, team_id: int, role_id: int, enabled: bool) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET enabled = ?
            WHERE team_id = ? AND role_id = ?
            """,
            (1 if enabled else 0, team_id, role_id),
        )
        self._conn.commit()

    def set_team_role_mode(self, team_id: int, role_id: int, mode: str) -> None:
        mode_value = str(mode).strip().lower()
        if mode_value not in {"normal", "orchestrator"}:
            raise ValueError(f"Unsupported team role mode: {mode!r}")
        cur = self._conn.cursor()
        if mode_value == "orchestrator":
            cur.execute(
                """
                UPDATE team_roles
                SET mode = 'normal'
                WHERE team_id = ? AND role_id != ?
                """,
                (team_id, role_id),
            )
        cur.execute(
            """
            UPDATE team_roles
            SET mode = ?, enabled = CASE WHEN ? = 'orchestrator' THEN 1 ELSE enabled END
            WHERE team_id = ? AND role_id = ?
            """,
            (mode_value, mode_value, team_id, role_id),
        )
        self._conn.commit()

    def deactivate_team_role(self, team_id: int, role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET is_active = 0, enabled = 0, mode = 'normal'
            WHERE team_id = ? AND role_id = ?
            """,
            (team_id, role_id),
        )
        self._conn.commit()

    def list_active_team_role_names(self) -> list[str]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT lower(role_name) AS role_name
            FROM team_roles
            WHERE is_active = 1 AND role_name IS NOT NULL AND trim(role_name) <> ''
            ORDER BY lower(role_name)
            """
        )
        rows = cur.fetchall()
        return [str(row["role_name"]) for row in rows]

    def deactivate_team_roles_by_role_name(self, role_name: str) -> int:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE team_roles
            SET is_active = 0, enabled = 0, mode = 'normal'
            WHERE is_active = 1 AND lower(role_name) = lower(?)
            """,
            (role_name,),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def ensure_group_role(self, group_id: int, role_id: int) -> GroupRole:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        return self.get_group_role(group_id, role_id)

    def get_group_role(self, group_id: int, role_id: int) -> GroupRole:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        team_role = self.get_team_role(team_id, role_id)
        return self._team_role_to_group_role(team_role, group_id)

    def list_group_roles(self, group_id: int) -> list[GroupRole]:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return [self._team_role_to_group_role(item, group_id) for item in self.list_team_roles(team_id)]

    def list_enabled_roles_for_group(self, group_id: int) -> list[GroupRole]:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return [self._team_role_to_group_role(item, group_id) for item in self.list_enabled_roles_for_team(team_id)]

    def get_enabled_orchestrator_for_group(self, group_id: int) -> GroupRole | None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        team_role = self.get_enabled_orchestrator_for_team(team_id)
        if team_role is None:
            return None
        return self._team_role_to_group_role(team_role, group_id)

    def list_roles_for_group(self, group_id: int) -> list[Role]:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return self.list_roles_for_team(team_id)

    def get_group_role_name(self, group_id: int, role_id: int) -> str:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return self.get_team_role_name(team_id, role_id)

    def get_role_for_group_by_name(self, group_id: int, role_name: str) -> Role:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return self.get_role_for_team_by_name(team_id, role_name)

    def group_role_name_exists(self, group_id: int, role_name: str, exclude_role_id: int | None = None) -> bool:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return self.team_role_name_exists(team_id, role_name, exclude_role_id=exclude_role_id)

    def update_role_name(self, role_id: int, role_name: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE roles SET role_name = ? WHERE role_id = ?",
            (role_name, role_id),
        )
        if self.has_team_role_name_binding():
            cur.execute(
                "UPDATE team_roles SET role_name = ? WHERE role_id = ?",
                (role_name, role_id),
            )
        if self.has_provider_user_data_role_name():
            cur.execute(
                "UPDATE provider_user_data SET role_name = ? WHERE role_id = ?",
                (role_name, role_id),
            )
        self._conn.commit()

    def delete_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.delete_user_role_session_by_team(telegram_user_id, team_id, role_id)

    def set_group_role_prompt(self, group_id: int, role_id: int, system_prompt_override: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_prompt(team_id, role_id, system_prompt_override)

    def set_group_role_display_name(self, group_id: int, role_id: int, display_name: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_display_name(team_id, role_id, display_name)

    def set_group_role_model(self, group_id: int, role_id: int, model_override: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_model(team_id, role_id, model_override)

    def set_group_role_extra_instruction(self, group_id: int, role_id: int, extra_instruction_override: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_extra_instruction(team_id, role_id, extra_instruction_override)

    def set_group_role_user_prompt_suffix(self, group_id: int, role_id: int, user_prompt_suffix: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_user_prompt_suffix(team_id, role_id, user_prompt_suffix)

    def set_group_role_user_reply_prefix(self, group_id: int, role_id: int, user_reply_prefix: str | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_user_reply_prefix(team_id, role_id, user_reply_prefix)

    def set_group_role_enabled(self, group_id: int, role_id: int, enabled: bool) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_enabled(team_id, role_id, enabled)

    def set_group_role_mode(self, group_id: int, role_id: int, mode: str) -> None:
        mode_value = str(mode).strip().lower()
        if mode_value not in {"normal", "orchestrator"}:
            raise ValueError(f"Unsupported group role mode: {mode!r}")
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.ensure_team_role(team_id, role_id)
        self.set_team_role_mode(team_id, role_id, mode_value)

    def deactivate_group_role(self, group_id: int, role_id: int) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.deactivate_team_role(team_id, role_id)

    def delete_role_if_unused(self, role_id: int) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM team_roles WHERE role_id = ? AND is_active = 1 LIMIT 1",
            (role_id,),
        )
        if cur.fetchone():
            return False
        cur.execute("DELETE FROM roles WHERE role_id = ?", (role_id,))
        self._conn.commit()
        return True

    def get_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> UserRoleSession | None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        return self.get_user_role_session_by_team(telegram_user_id, team_id, role_id)

    def get_user_role_session_by_team(self, telegram_user_id: int, team_id: int, role_id: int) -> UserRoleSession | None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if self.has_session_team_role_id() and team_role_id is not None:
            return self.get_user_role_session_by_team_role(telegram_user_id, team_role_id)
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT telegram_user_id, team_id, role_id, team_role_id, session_id, created_at, last_used_at
            FROM user_role_sessions
            WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
            LIMIT 1
            """,
            (telegram_user_id, team_id, role_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return UserRoleSession(
            telegram_user_id=row["telegram_user_id"],
            group_id=self.resolve_telegram_chat_id_by_team_id(team_id) or 0,
            team_id=row["team_id"],
            role_id=row["role_id"],
            team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )

    def get_user_role_session_by_team_role(self, telegram_user_id: int, team_role_id: int) -> UserRoleSession | None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return None
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_session_team_role_id():
            cur.execute(
                """
                SELECT telegram_user_id, team_id, role_id, team_role_id, session_id, created_at, last_used_at
                FROM user_role_sessions
                WHERE telegram_user_id = ? AND team_role_id = ?
                LIMIT 1
                """,
                (telegram_user_id, team_role_id),
            )
        else:
            cur.execute(
                """
                SELECT telegram_user_id, team_id, role_id, NULL as team_role_id, session_id, created_at, last_used_at
                FROM user_role_sessions
                WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                LIMIT 1
                """,
                (telegram_user_id, team_id, role_id),
            )
        row = cur.fetchone()
        if not row:
            return None
        return UserRoleSession(
            telegram_user_id=row["telegram_user_id"],
            group_id=self.resolve_telegram_chat_id_by_team_id(team_id) or 0,
            team_id=team_id,
            role_id=role_id,
            team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )

    def save_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int, session_id: str) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.save_user_role_session_by_team(telegram_user_id, team_id, role_id, session_id)

    def save_user_role_session_by_team(self, telegram_user_id: int, team_id: int, role_id: int, session_id: str) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id, ensure_exists=True)
        if team_role_id is not None:
            self.save_user_role_session_by_team_role(telegram_user_id, team_role_id, session_id)
            return
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO user_role_sessions (telegram_user_id, team_id, role_id, session_id, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id, team_id, role_id) DO UPDATE SET
                session_id=excluded.session_id,
                last_used_at=excluded.last_used_at
            """,
            (telegram_user_id, team_id, role_id, session_id, now, now),
        )
        self._conn.commit()

    def save_user_role_session_by_team_role(self, telegram_user_id: int, team_role_id: int, session_id: str) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            raise ValueError(f"Team role not found: team_role_id={team_role_id}")
        team_id, role_id = identity
        now = _utc_now()
        cur = self._conn.cursor()
        if self.has_session_team_role_id():
            cur.execute(
                """
                INSERT INTO user_role_sessions (
                    telegram_user_id, team_id, role_id, team_role_id, session_id, created_at, last_used_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, team_id, role_id) DO UPDATE SET
                    team_role_id=excluded.team_role_id,
                    session_id=excluded.session_id,
                    last_used_at=excluded.last_used_at
                """,
                (telegram_user_id, team_id, role_id, team_role_id, session_id, now, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO user_role_sessions (telegram_user_id, team_id, role_id, session_id, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id, team_id, role_id) DO UPDATE SET
                    session_id=excluded.session_id,
                    last_used_at=excluded.last_used_at
                """,
                (telegram_user_id, team_id, role_id, session_id, now, now),
            )
        self._conn.commit()

    def delete_user_role_session_by_team(self, telegram_user_id: int, team_id: int, role_id: int) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if self.has_session_team_role_id() and team_role_id is not None:
            self.delete_user_role_session_by_team_role(telegram_user_id, team_role_id)
            return
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM user_role_sessions
            WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
            """,
            (telegram_user_id, team_id, role_id),
        )
        self._conn.commit()

    def delete_user_role_session_by_team_role(self, telegram_user_id: int, team_role_id: int) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_session_team_role_id():
            cur.execute(
                """
                DELETE FROM user_role_sessions
                WHERE telegram_user_id = ? AND team_role_id = ?
                """,
                (telegram_user_id, team_role_id),
            )
        else:
            cur.execute(
                """
                DELETE FROM user_role_sessions
                WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                """,
                (telegram_user_id, team_id, role_id),
            )
        self._conn.commit()

    def touch_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.touch_user_role_session_by_team(telegram_user_id, team_id, role_id)

    def touch_user_role_session_by_team(self, telegram_user_id: int, team_id: int, role_id: int) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if self.has_session_team_role_id() and team_role_id is not None:
            self.touch_user_role_session_by_team_role(telegram_user_id, team_role_id)
            return
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE user_role_sessions
            SET last_used_at = ?
            WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
            """,
            (now, telegram_user_id, team_id, role_id),
        )
        self._conn.commit()

    def touch_user_role_session_by_team_role(self, telegram_user_id: int, team_role_id: int) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        now = _utc_now()
        cur = self._conn.cursor()
        if self.has_session_team_role_id():
            cur.execute(
                """
                UPDATE user_role_sessions
                SET last_used_at = ?
                WHERE telegram_user_id = ? AND team_role_id = ?
                """,
                (now, telegram_user_id, team_role_id),
            )
        else:
            cur.execute(
                """
                UPDATE user_role_sessions
                SET last_used_at = ?
                WHERE telegram_user_id = ? AND team_id = ? AND role_id = ?
                """,
                (now, telegram_user_id, team_id, role_id),
            )
        self._conn.commit()

    def list_user_sessions(self, telegram_user_id: int) -> list[str]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT session_id FROM user_role_sessions WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        return [row["session_id"] for row in cur.fetchall()]

    def find_team_role_id_by_session_id(self, session_id: str) -> int | None:
        cur = self._conn.cursor()
        if self.has_session_team_role_id():
            cur.execute(
                """
                SELECT team_role_id
                FROM user_role_sessions
                WHERE session_id = ? AND team_role_id IS NOT NULL
                ORDER BY last_used_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cur.fetchone()
            if row and row["team_role_id"] is not None:
                return int(row["team_role_id"])
        cur.execute(
            """
            SELECT team_id, role_id
            FROM user_role_sessions
            WHERE session_id = ?
            ORDER BY last_used_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        team_role_id = self.resolve_team_role_id(int(row["team_id"]), int(row["role_id"]))
        return int(team_role_id) if team_role_id is not None else None

    def upsert_role_prepost_processing(
        self,
        group_id: int,
        role_id: int,
        prepost_processing_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RolePrePostProcessing:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        got = self.upsert_role_prepost_processing_for_team(
            team_id,
            role_id,
            prepost_processing_id,
            enabled=enabled,
            config=config,
        )
        return RolePrePostProcessing(
            group_id=group_id,
            role_id=got.role_id,
            team_role_id=got.team_role_id,
            prepost_processing_id=got.prepost_processing_id,
            enabled=got.enabled,
            config_json=got.config_json,
            created_at=got.created_at,
            updated_at=got.updated_at,
        )

    def get_role_prepost_processing(self, group_id: int, role_id: int, prepost_processing_id: str) -> RolePrePostProcessing | None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        got = self.get_role_prepost_processing_for_team(team_id, role_id, prepost_processing_id)
        if got is None:
            return None
        return RolePrePostProcessing(
            group_id=group_id,
            role_id=got.role_id,
            team_role_id=got.team_role_id,
            prepost_processing_id=got.prepost_processing_id,
            enabled=got.enabled,
            config_json=got.config_json,
            created_at=got.created_at,
            updated_at=got.updated_at,
        )

    def list_role_prepost_processing(self, group_id: int, role_id: int, *, enabled_only: bool = False) -> list[RolePrePostProcessing]:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        rows = self.list_role_prepost_processing_for_team(team_id, role_id, enabled_only=enabled_only)
        return [
            RolePrePostProcessing(
                group_id=group_id,
                role_id=row.role_id,
                team_role_id=row.team_role_id,
                prepost_processing_id=row.prepost_processing_id,
                enabled=row.enabled,
                config_json=row.config_json,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def list_role_prepost_processing_for_team(self, team_id: int, role_id: int, *, enabled_only: bool = False) -> list[RolePrePostProcessing]:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return []
        return self.list_role_prepost_processing_for_team_role(team_role_id, enabled_only=enabled_only)

    def list_role_prepost_processing_for_team_role(self, team_role_id: int, *, enabled_only: bool = False) -> list[RolePrePostProcessing]:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return []
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            if enabled_only:
                cur.execute(
                    """
                    SELECT team_id, role_id, team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                    FROM role_prepost_processing
                    WHERE team_role_id = ? AND enabled = 1
                    ORDER BY prepost_processing_id
                    """,
                    (team_role_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT team_id, role_id, team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                    FROM role_prepost_processing
                    WHERE team_role_id = ?
                    ORDER BY prepost_processing_id
                    """,
                    (team_role_id,),
                )
        elif enabled_only:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                FROM role_prepost_processing
                WHERE team_id = ? AND role_id = ? AND enabled = 1
                ORDER BY prepost_processing_id
                """,
                (team_id, role_id),
            )
        else:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                FROM role_prepost_processing
                WHERE team_id = ? AND role_id = ?
                ORDER BY prepost_processing_id
                """,
                (team_id, role_id),
            )
        group_id = self.resolve_telegram_chat_id_by_team_id(team_id) or 0
        rows = cur.fetchall()
        return [
            RolePrePostProcessing(
                group_id=group_id,
                role_id=row["role_id"],
                team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
                prepost_processing_id=row["prepost_processing_id"],
                enabled=bool(row["enabled"]),
                config_json=row["config_json"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def upsert_role_prepost_processing_for_team(
        self,
        team_id: int,
        role_id: int,
        prepost_processing_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RolePrePostProcessing:
        team_role_id = self.resolve_team_role_id(team_id, role_id, ensure_exists=True)
        if team_role_id is None:
            raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
        return self.upsert_role_prepost_processing_for_team_role(
            team_role_id, prepost_processing_id, enabled=enabled, config=config
        )

    def upsert_role_prepost_processing_for_team_role(
        self,
        team_role_id: int,
        prepost_processing_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RolePrePostProcessing:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            raise ValueError(f"Team role not found: team_role_id={team_role_id}")
        team_id, role_id = identity
        now = _utc_now()
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            cur.execute(
                """
                INSERT INTO role_prepost_processing (
                    team_id, role_id, team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, role_id, prepost_processing_id) DO UPDATE SET
                    team_role_id=excluded.team_role_id,
                    enabled=excluded.enabled,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (team_id, role_id, team_role_id, prepost_processing_id, 1 if enabled else 0, config_json, now, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO role_prepost_processing (team_id, role_id, prepost_processing_id, enabled, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, role_id, prepost_processing_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (team_id, role_id, prepost_processing_id, 1 if enabled else 0, config_json, now, now),
            )
        self._conn.commit()
        got = self.get_role_prepost_processing_for_team_role(team_role_id, prepost_processing_id)
        if got is None:
            raise RuntimeError("Failed to upsert team role pre/post processing")
        return got

    def get_role_prepost_processing_for_team(self, team_id: int, role_id: int, prepost_processing_id: str) -> RolePrePostProcessing | None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return None
        return self.get_role_prepost_processing_for_team_role(team_role_id, prepost_processing_id)

    def get_role_prepost_processing_for_team_role(self, team_role_id: int, prepost_processing_id: str) -> RolePrePostProcessing | None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return None
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            cur.execute(
                """
                SELECT team_id, role_id, team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                FROM role_prepost_processing
                WHERE team_role_id = ? AND prepost_processing_id = ?
                """,
                (team_role_id, prepost_processing_id),
            )
        else:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, prepost_processing_id, enabled, config_json, created_at, updated_at
                FROM role_prepost_processing
                WHERE team_id = ? AND role_id = ? AND prepost_processing_id = ?
                """,
                (team_id, role_id, prepost_processing_id),
            )
        row = cur.fetchone()
        if not row:
            return None
        return RolePrePostProcessing(
            group_id=self.resolve_telegram_chat_id_by_team_id(team_id) or 0,
            role_id=row["role_id"],
            team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
            prepost_processing_id=row["prepost_processing_id"],
            enabled=bool(row["enabled"]),
            config_json=row["config_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def set_role_prepost_processing_enabled_for_team(
        self,
        team_id: int,
        role_id: int,
        prepost_processing_id: str,
        enabled: bool,
    ) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.set_role_prepost_processing_enabled_for_team_role(team_role_id, prepost_processing_id, enabled)

    def set_role_prepost_processing_enabled_for_team_role(
        self,
        team_role_id: int,
        prepost_processing_id: str,
        enabled: bool,
    ) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        now = _utc_now()
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            cur.execute(
                """
                UPDATE role_prepost_processing
                SET enabled = ?, updated_at = ?
                WHERE team_role_id = ? AND prepost_processing_id = ?
                """,
                (1 if enabled else 0, now, team_role_id, prepost_processing_id),
            )
        else:
            cur.execute(
                """
                UPDATE role_prepost_processing
                SET enabled = ?, updated_at = ?
                WHERE team_id = ? AND role_id = ? AND prepost_processing_id = ?
                """,
                (1 if enabled else 0, now, team_id, role_id, prepost_processing_id),
            )
        self._conn.commit()

    def set_role_prepost_processing_config_for_team(
        self,
        team_id: int,
        role_id: int,
        prepost_processing_id: str,
        config: dict | None,
    ) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.set_role_prepost_processing_config_for_team_role(team_role_id, prepost_processing_id, config)

    def set_role_prepost_processing_config_for_team_role(
        self,
        team_role_id: int,
        prepost_processing_id: str,
        config: dict | None,
    ) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        now = _utc_now()
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            cur.execute(
                """
                UPDATE role_prepost_processing
                SET config_json = ?, updated_at = ?
                WHERE team_role_id = ? AND prepost_processing_id = ?
                """,
                (config_json, now, team_role_id, prepost_processing_id),
            )
        else:
            cur.execute(
                """
                UPDATE role_prepost_processing
                SET config_json = ?, updated_at = ?
                WHERE team_id = ? AND role_id = ? AND prepost_processing_id = ?
                """,
                (config_json, now, team_id, role_id, prepost_processing_id),
            )
        self._conn.commit()

    def delete_role_prepost_processing_for_team(self, team_id: int, role_id: int, prepost_processing_id: str) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.delete_role_prepost_processing_for_team_role(team_role_id, prepost_processing_id)

    def delete_role_prepost_processing_for_team_role(self, team_role_id: int, prepost_processing_id: str) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_prepost_team_role_id():
            cur.execute(
                """
                DELETE FROM role_prepost_processing
                WHERE team_role_id = ? AND prepost_processing_id = ?
                """,
                (team_role_id, prepost_processing_id),
            )
        else:
            cur.execute(
                """
                DELETE FROM role_prepost_processing
                WHERE team_id = ? AND role_id = ? AND prepost_processing_id = ?
                """,
                (team_id, role_id, prepost_processing_id),
            )
        self._conn.commit()

    def set_role_prepost_processing_enabled(self, group_id: int, role_id: int, prepost_processing_id: str, enabled: bool) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.set_role_prepost_processing_enabled_for_team(team_id, role_id, prepost_processing_id, enabled)

    def set_role_prepost_processing_config(self, group_id: int, role_id: int, prepost_processing_id: str, config: dict | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.set_role_prepost_processing_config_for_team(team_id, role_id, prepost_processing_id, config)

    def delete_role_prepost_processing(self, group_id: int, role_id: int, prepost_processing_id: str) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.delete_role_prepost_processing_for_team(team_id, role_id, prepost_processing_id)

    def upsert_role_skill(
        self,
        group_id: int,
        role_id: int,
        skill_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RoleSkill:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        got = self.upsert_role_skill_for_team(team_id, role_id, skill_id, enabled=enabled, config=config)
        return RoleSkill(
            group_id=group_id,
            role_id=got.role_id,
            team_role_id=got.team_role_id,
            skill_id=got.skill_id,
            enabled=got.enabled,
            config_json=got.config_json,
            created_at=got.created_at,
            updated_at=got.updated_at,
        )

    def get_role_skill(self, group_id: int, role_id: int, skill_id: str) -> RoleSkill | None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        got = self.get_role_skill_for_team(team_id, role_id, skill_id)
        if got is None:
            return None
        return RoleSkill(
            group_id=group_id,
            role_id=got.role_id,
            team_role_id=got.team_role_id,
            skill_id=got.skill_id,
            enabled=got.enabled,
            config_json=got.config_json,
            created_at=got.created_at,
            updated_at=got.updated_at,
        )

    def list_role_skills(self, group_id: int, role_id: int, *, enabled_only: bool = False) -> list[RoleSkill]:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        rows = self.list_role_skills_for_team(team_id, role_id, enabled_only=enabled_only)
        return [
            RoleSkill(
                group_id=group_id,
                role_id=row.role_id,
                team_role_id=row.team_role_id,
                skill_id=row.skill_id,
                enabled=row.enabled,
                config_json=row.config_json,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def list_role_skills_for_team(self, team_id: int, role_id: int, *, enabled_only: bool = False) -> list[RoleSkill]:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return []
        return self.list_role_skills_for_team_role(team_role_id, enabled_only=enabled_only)

    def list_role_skills_for_team_role(self, team_role_id: int, *, enabled_only: bool = False) -> list[RoleSkill]:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return []
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            if enabled_only:
                cur.execute(
                    """
                    SELECT team_id, role_id, team_role_id, skill_id, enabled, config_json, created_at, updated_at
                    FROM role_skills_enabled
                    WHERE team_role_id = ? AND enabled = 1
                    ORDER BY skill_id
                    """,
                    (team_role_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT team_id, role_id, team_role_id, skill_id, enabled, config_json, created_at, updated_at
                    FROM role_skills_enabled
                    WHERE team_role_id = ?
                    ORDER BY skill_id
                    """,
                    (team_role_id,),
                )
        elif enabled_only:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, skill_id, enabled, config_json, created_at, updated_at
                FROM role_skills_enabled
                WHERE team_id = ? AND role_id = ? AND enabled = 1
                ORDER BY skill_id
                """,
                (team_id, role_id),
            )
        else:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, skill_id, enabled, config_json, created_at, updated_at
                FROM role_skills_enabled
                WHERE team_id = ? AND role_id = ?
                ORDER BY skill_id
                """,
                (team_id, role_id),
            )
        group_id = self.resolve_telegram_chat_id_by_team_id(team_id) or 0
        rows = cur.fetchall()
        return [
            RoleSkill(
                group_id=group_id,
                role_id=row["role_id"],
                team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
                skill_id=row["skill_id"],
                enabled=bool(row["enabled"]),
                config_json=row["config_json"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def upsert_role_skill_for_team(
        self,
        team_id: int,
        role_id: int,
        skill_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RoleSkill:
        team_role_id = self.resolve_team_role_id(team_id, role_id, ensure_exists=True)
        if team_role_id is None:
            raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
        return self.upsert_role_skill_for_team_role(team_role_id, skill_id, enabled=enabled, config=config)

    def upsert_role_skill_for_team_role(
        self,
        team_role_id: int,
        skill_id: str,
        *,
        enabled: bool = True,
        config: dict | None = None,
    ) -> RoleSkill:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            raise ValueError(f"Team role not found: team_role_id={team_role_id}")
        team_id, role_id = identity
        now = _utc_now()
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            cur.execute(
                """
                INSERT INTO role_skills_enabled (
                    team_id, role_id, team_role_id, skill_id, enabled, config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, role_id, skill_id) DO UPDATE SET
                    team_role_id=excluded.team_role_id,
                    enabled=excluded.enabled,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (team_id, role_id, team_role_id, skill_id, 1 if enabled else 0, config_json, now, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO role_skills_enabled (team_id, role_id, skill_id, enabled, config_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id, role_id, skill_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (team_id, role_id, skill_id, 1 if enabled else 0, config_json, now, now),
            )
        self._conn.commit()
        got = self.get_role_skill_for_team_role(team_role_id, skill_id)
        if got is None:
            raise RuntimeError("Failed to upsert team role skill")
        return got

    def get_role_skill_for_team(self, team_id: int, role_id: int, skill_id: str) -> RoleSkill | None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return None
        return self.get_role_skill_for_team_role(team_role_id, skill_id)

    def get_role_skill_for_team_role(self, team_role_id: int, skill_id: str) -> RoleSkill | None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return None
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            cur.execute(
                """
                SELECT team_id, role_id, team_role_id, skill_id, enabled, config_json, created_at, updated_at
                FROM role_skills_enabled
                WHERE team_role_id = ? AND skill_id = ?
                """,
                (team_role_id, skill_id),
            )
        else:
            cur.execute(
                """
                SELECT team_id, role_id, NULL AS team_role_id, skill_id, enabled, config_json, created_at, updated_at
                FROM role_skills_enabled
                WHERE team_id = ? AND role_id = ? AND skill_id = ?
                """,
                (team_id, role_id, skill_id),
            )
        row = cur.fetchone()
        if not row:
            return None
        return RoleSkill(
            group_id=self.resolve_telegram_chat_id_by_team_id(team_id) or 0,
            role_id=row["role_id"],
            team_role_id=row["team_role_id"] if "team_role_id" in row.keys() else None,
            skill_id=row["skill_id"],
            enabled=bool(row["enabled"]),
            config_json=row["config_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def set_role_skill_enabled_for_team(self, team_id: int, role_id: int, skill_id: str, enabled: bool) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.set_role_skill_enabled_for_team_role(team_role_id, skill_id, enabled)

    def set_role_skill_enabled_for_team_role(self, team_role_id: int, skill_id: str, enabled: bool) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        now = _utc_now()
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            cur.execute(
                """
                UPDATE role_skills_enabled
                SET enabled = ?, updated_at = ?
                WHERE team_role_id = ? AND skill_id = ?
                """,
                (1 if enabled else 0, now, team_role_id, skill_id),
            )
        else:
            cur.execute(
                """
                UPDATE role_skills_enabled
                SET enabled = ?, updated_at = ?
                WHERE team_id = ? AND role_id = ? AND skill_id = ?
                """,
                (1 if enabled else 0, now, team_id, role_id, skill_id),
            )
        self._conn.commit()

    def set_role_skill_config_for_team(self, team_id: int, role_id: int, skill_id: str, config: dict | None) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.set_role_skill_config_for_team_role(team_role_id, skill_id, config)

    def set_role_skill_config_for_team_role(self, team_role_id: int, skill_id: str, config: dict | None) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        now = _utc_now()
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            cur.execute(
                """
                UPDATE role_skills_enabled
                SET config_json = ?, updated_at = ?
                WHERE team_role_id = ? AND skill_id = ?
                """,
                (config_json, now, team_role_id, skill_id),
            )
        else:
            cur.execute(
                """
                UPDATE role_skills_enabled
                SET config_json = ?, updated_at = ?
                WHERE team_id = ? AND role_id = ? AND skill_id = ?
                """,
                (config_json, now, team_id, role_id, skill_id),
            )
        self._conn.commit()

    def delete_role_skill_for_team(self, team_id: int, role_id: int, skill_id: str) -> None:
        team_role_id = self.resolve_team_role_id(team_id, role_id)
        if team_role_id is None:
            return
        self.delete_role_skill_for_team_role(team_role_id, skill_id)

    def delete_role_skill_for_team_role(self, team_role_id: int, skill_id: str) -> None:
        identity = self.resolve_team_role_identity(team_role_id)
        if identity is None:
            return
        team_id, role_id = identity
        cur = self._conn.cursor()
        if self.has_skill_team_role_id():
            cur.execute(
                """
                DELETE FROM role_skills_enabled
                WHERE team_role_id = ? AND skill_id = ?
                """,
                (team_role_id, skill_id),
            )
        else:
            cur.execute(
                """
                DELETE FROM role_skills_enabled
                WHERE team_id = ? AND role_id = ? AND skill_id = ?
                """,
                (team_id, role_id, skill_id),
            )
        self._conn.commit()

    def clone_team_role_processing_bindings(self, source_team_role_id: int, target_team_role_id: int) -> None:
        source_identity = self.resolve_team_role_identity(source_team_role_id)
        target_identity = self.resolve_team_role_identity(target_team_role_id)
        if source_identity is None or target_identity is None:
            raise ValueError("Team role not found for clone")

        for item in self.list_role_prepost_processing_for_team_role(source_team_role_id, enabled_only=False):
            config = None
            if item.config_json:
                try:
                    loaded = json.loads(item.config_json)
                    if isinstance(loaded, dict):
                        config = loaded
                except Exception:
                    config = None
            self.upsert_role_prepost_processing_for_team_role(
                target_team_role_id,
                item.prepost_processing_id,
                enabled=item.enabled,
                config=config,
            )

        for item in self.list_role_skills_for_team_role(source_team_role_id, enabled_only=False):
            config = None
            if item.config_json:
                try:
                    loaded = json.loads(item.config_json)
                    if isinstance(loaded, dict):
                        config = loaded
                except Exception:
                    config = None
            self.upsert_role_skill_for_team_role(
                target_team_role_id,
                item.skill_id,
                enabled=item.enabled,
                config=config,
            )

    def set_role_skill_enabled(self, group_id: int, role_id: int, skill_id: str, enabled: bool) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.set_role_skill_enabled_for_team(team_id, role_id, skill_id, enabled)

    def set_role_skill_config(self, group_id: int, role_id: int, skill_id: str, config: dict | None) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.set_role_skill_config_for_team(team_id, role_id, skill_id, config)

    def delete_role_skill(self, group_id: int, role_id: int, skill_id: str) -> None:
        team_id = self.resolve_team_id_by_group_id_legacy(group_id)
        self.delete_role_skill_for_team(team_id, role_id, skill_id)
