from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.models import AuthToken, Group, GroupRole, Role, User, UserRoleSession


@dataclass
class SessionResolution:
    role: Role
    session: UserRoleSession | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _table_has_column(self, table: str, column: str) -> bool:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        return any(row["name"] == column for row in cur.fetchall())

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in cur.fetchall()}
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            self._conn.commit()

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
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                title TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
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
            CREATE TABLE IF NOT EXISTS group_roles (
                group_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                system_prompt_override TEXT,
                display_name TEXT,
                model_override TEXT,
                user_prompt_suffix TEXT,
                user_reply_prefix TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (group_id, role_id),
                FOREIGN KEY (group_id) REFERENCES groups(group_id),
                FOREIGN KEY (role_id) REFERENCES roles(role_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_role_sessions (
                telegram_user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL DEFAULT 0,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (telegram_user_id, group_id, role_id),
                FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                FOREIGN KEY (group_id) REFERENCES groups(group_id),
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
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (provider_id, key, role_id)
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_runs_user_created ON tool_runs(telegram_user_id, created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tool_runs_tool_created ON tool_runs(tool_name, created_at)")
        self._conn.commit()

        # Backwards-compatible migrations for existing DBs
        self._ensure_column("users", "is_authorized", "is_authorized INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("group_roles", "display_name", "display_name TEXT")
        self._ensure_column("group_roles", "model_override", "model_override TEXT")
        self._ensure_column("group_roles", "user_prompt_suffix", "user_prompt_suffix TEXT")
        self._ensure_column("group_roles", "user_reply_prefix", "user_reply_prefix TEXT")
        self._migrate_user_role_sessions()

    def _migrate_user_role_sessions(self) -> None:
        if not self._table_has_column("user_role_sessions", "group_id"):
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_role_sessions_v2 (
                    telegram_user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_user_id, group_id, role_id),
                    FOREIGN KEY (telegram_user_id) REFERENCES users(telegram_user_id),
                    FOREIGN KEY (group_id) REFERENCES groups(group_id),
                    FOREIGN KEY (role_id) REFERENCES roles(role_id)
                )
                """
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO user_role_sessions_v2
                    (telegram_user_id, role_id, group_id, session_id, created_at, last_used_at)
                SELECT telegram_user_id, role_id, 0, session_id, created_at, last_used_at
                FROM user_role_sessions
                """
            )
            cur.execute("DROP TABLE user_role_sessions")
            cur.execute("ALTER TABLE user_role_sessions_v2 RENAME TO user_role_sessions")
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
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO groups (group_id, title, is_active, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                title=excluded.title,
                is_active=1
            """,
            (group_id, title, now),
        )
        self._conn.commit()
        return self.get_group(group_id)

    def get_group(self, group_id: int) -> Group:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT group_id, title, is_active, created_at FROM groups WHERE group_id = ?",
            (group_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Group not found: {group_id}")
        return Group(
            group_id=row["group_id"],
            title=row["title"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )

    def list_groups(self) -> list[Group]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT group_id, title, is_active, created_at FROM groups WHERE is_active = 1 ORDER BY group_id"
        )
        rows = cur.fetchall()
        return [
            Group(
                group_id=row["group_id"],
                title=row["title"],
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

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

    def set_group_active(self, group_id: int, is_active: bool) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE groups SET is_active = ? WHERE group_id = ?",
            (1 if is_active else 0, group_id),
        )
        self._conn.commit()

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
        return Role(
            role_id=row["role_id"],
            role_name=row["role_name"],
            description=row["description"],
            base_system_prompt=row["base_system_prompt"],
            extra_instruction=row["extra_instruction"],
            llm_model=row["llm_model"],
            is_active=bool(row["is_active"]),
        )

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
        return Role(
            role_id=row["role_id"],
            role_name=row["role_name"],
            description=row["description"],
            base_system_prompt=row["base_system_prompt"],
            extra_instruction=row["extra_instruction"],
            llm_model=row["llm_model"],
            is_active=bool(row["is_active"]),
        )

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
        return [
            Role(
                role_id=row["role_id"],
                role_name=row["role_name"],
                description=row["description"],
                base_system_prompt=row["base_system_prompt"],
                extra_instruction=row["extra_instruction"],
                llm_model=row["llm_model"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def ensure_group_role(self, group_id: int, role_id: int) -> GroupRole:
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO group_roles (
                group_id,
                role_id,
                system_prompt_override,
                display_name,
                model_override,
                user_prompt_suffix,
                user_reply_prefix,
                is_active
            )
            VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, 1)
            ON CONFLICT(group_id, role_id) DO NOTHING
            """,
            (group_id, role_id),
        )
        self._conn.commit()
        return self.get_group_role(group_id, role_id)

    def get_group_role(self, group_id: int, role_id: int) -> GroupRole:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT group_id, role_id, system_prompt_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, is_active
            FROM group_roles
            WHERE group_id = ? AND role_id = ?
            """,
            (group_id, role_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Group role not found: group_id={group_id} role_id={role_id}")
        return GroupRole(
            group_id=row["group_id"],
            role_id=row["role_id"],
            system_prompt_override=row["system_prompt_override"],
            display_name=row["display_name"],
            model_override=row["model_override"],
            user_prompt_suffix=row["user_prompt_suffix"],
            user_reply_prefix=row["user_reply_prefix"],
            is_active=bool(row["is_active"]),
        )

    def list_group_roles(self, group_id: int) -> list[GroupRole]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT group_id, role_id, system_prompt_override, display_name, model_override, user_prompt_suffix, user_reply_prefix, is_active
            FROM group_roles
            WHERE group_id = ? AND is_active = 1
            ORDER BY role_id
            """,
            (group_id,),
        )
        rows = cur.fetchall()
        return [
            GroupRole(
                group_id=row["group_id"],
                role_id=row["role_id"],
                system_prompt_override=row["system_prompt_override"],
                display_name=row["display_name"],
                model_override=row["model_override"],
                user_prompt_suffix=row["user_prompt_suffix"],
                user_reply_prefix=row["user_reply_prefix"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def list_roles_for_group(self, group_id: int) -> list[Role]:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT r.role_id, r.role_name, r.description, r.base_system_prompt, r.extra_instruction, r.llm_model, r.is_active
            FROM roles r
            JOIN group_roles gr ON gr.role_id = r.role_id
            WHERE gr.group_id = ? AND gr.is_active = 1 AND r.is_active = 1
            ORDER BY r.role_name
            """,
            (group_id,),
        )
        rows = cur.fetchall()
        return [
            Role(
                role_id=row["role_id"],
                role_name=row["role_name"],
                description=row["description"],
                base_system_prompt=row["base_system_prompt"],
                extra_instruction=row["extra_instruction"],
                llm_model=row["llm_model"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    def update_role_name(self, role_id: int, role_name: str) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE roles SET role_name = ? WHERE role_id = ?",
            (role_name, role_id),
        )
        self._conn.commit()

    def delete_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM user_role_sessions
            WHERE telegram_user_id = ? AND group_id = ? AND role_id = ?
            """,
            (telegram_user_id, group_id, role_id),
        )
        self._conn.commit()

    def set_group_role_prompt(self, group_id: int, role_id: int, system_prompt_override: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE group_roles
            SET system_prompt_override = ?
            WHERE group_id = ? AND role_id = ?
            """,
            (system_prompt_override, group_id, role_id),
        )
        self._conn.commit()

    def set_group_role_display_name(self, group_id: int, role_id: int, display_name: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE group_roles
            SET display_name = ?
            WHERE group_id = ? AND role_id = ?
            """,
            (display_name, group_id, role_id),
        )
        self._conn.commit()

    def set_group_role_model(self, group_id: int, role_id: int, model_override: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE group_roles
            SET model_override = ?
            WHERE group_id = ? AND role_id = ?
            """,
            (model_override, group_id, role_id),
        )
        self._conn.commit()

    def set_group_role_user_prompt_suffix(self, group_id: int, role_id: int, user_prompt_suffix: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE group_roles
            SET user_prompt_suffix = ?
            WHERE group_id = ? AND role_id = ?
            """,
            (user_prompt_suffix, group_id, role_id),
        )
        self._conn.commit()

    def set_group_role_user_reply_prefix(self, group_id: int, role_id: int, user_reply_prefix: str | None) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE group_roles
            SET user_reply_prefix = ?
            WHERE group_id = ? AND role_id = ?
            """,
            (user_reply_prefix, group_id, role_id),
        )
        self._conn.commit()

    def deactivate_group_role(self, group_id: int, role_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE group_roles SET is_active = 0 WHERE group_id = ? AND role_id = ?",
            (group_id, role_id),
        )
        self._conn.commit()

    def delete_role_if_unused(self, role_id: int) -> bool:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT 1 FROM group_roles WHERE role_id = ? AND is_active = 1 LIMIT 1",
            (role_id,),
        )
        if cur.fetchone():
            return False
        cur.execute("DELETE FROM roles WHERE role_id = ?", (role_id,))
        self._conn.commit()
        return True

    def get_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> UserRoleSession | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT telegram_user_id, group_id, role_id, session_id, created_at, last_used_at
            FROM user_role_sessions
            WHERE telegram_user_id = ? AND group_id = ? AND role_id = ?
            """,
            (telegram_user_id, group_id, role_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return UserRoleSession(
            telegram_user_id=row["telegram_user_id"],
            group_id=row["group_id"],
            role_id=row["role_id"],
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
        )

    def save_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int, session_id: str) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO user_role_sessions (telegram_user_id, group_id, role_id, session_id, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id, group_id, role_id) DO UPDATE SET
                session_id=excluded.session_id,
                last_used_at=excluded.last_used_at
            """,
            (telegram_user_id, group_id, role_id, session_id, now, now),
        )
        self._conn.commit()

    def touch_user_role_session(self, telegram_user_id: int, group_id: int, role_id: int) -> None:
        now = _utc_now()
        cur = self._conn.cursor()
        cur.execute(
            """
            UPDATE user_role_sessions
            SET last_used_at = ?
            WHERE telegram_user_id = ? AND group_id = ? AND role_id = ?
            """,
            (now, telegram_user_id, group_id, role_id),
        )
        self._conn.commit()

    def list_user_sessions(self, telegram_user_id: int) -> list[str]:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT session_id FROM user_role_sessions WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        return [row["session_id"] for row in cur.fetchall()]
