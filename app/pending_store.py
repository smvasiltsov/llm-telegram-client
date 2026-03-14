from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


class PendingMessageRecord(TypedDict):
    chat_id: int
    team_id: int
    message_id: int
    role_name: str
    content: str
    reply_text: str | None


class PendingStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_messages (
                telegram_user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                role_name TEXT NOT NULL,
                content TEXT NOT NULL,
                reply_text TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

        self._ensure_column("pending_messages", "reply_text", "reply_text TEXT")
        self._ensure_column("pending_messages", "team_id", "team_id INTEGER")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in cur.fetchall()}
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            self._conn.commit()

    def save(
        self,
        telegram_user_id: int,
        chat_id: int,
        message_id: int,
        role_name: str,
        content: str,
        reply_text: str | None = None,
        team_id: int | None = None,
    ) -> None:
        if team_id is None:
            raise ValueError("team_id is required for pending message")
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO pending_messages (telegram_user_id, chat_id, team_id, message_id, role_name, content, reply_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id=excluded.chat_id,
                team_id=excluded.team_id,
                message_id=excluded.message_id,
                role_name=excluded.role_name,
                content=excluded.content,
                reply_text=excluded.reply_text,
                created_at=excluded.created_at
            """,
            (telegram_user_id, chat_id, int(team_id), message_id, role_name, content, reply_text, now),
        )
        self._conn.commit()

    def pop(self, telegram_user_id: int) -> tuple[int, int, str, str, str | None] | None:
        record = self.pop_record(telegram_user_id)
        if record is None:
            return None
        return (
            record["chat_id"],
            record["message_id"],
            record["role_name"],
            record["content"],
            record["reply_text"],
        )

    def pop_record(self, telegram_user_id: int) -> PendingMessageRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT chat_id, team_id, message_id, role_name, content, reply_text FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["team_id"] is None:
            cur.execute("DELETE FROM pending_messages WHERE telegram_user_id = ?", (telegram_user_id,))
            self._conn.commit()
            return None
        cur.execute(
            "DELETE FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        self._conn.commit()
        return {
            "chat_id": int(row["chat_id"]),
            "team_id": int(row["team_id"]),
            "message_id": int(row["message_id"]),
            "role_name": str(row["role_name"]),
            "content": str(row["content"]),
            "reply_text": row["reply_text"],
        }

    def peek(self, telegram_user_id: int) -> tuple[int, int, str, str, str | None] | None:
        record = self.peek_record(telegram_user_id)
        if record is None:
            return None
        return (
            record["chat_id"],
            record["message_id"],
            record["role_name"],
            record["content"],
            record["reply_text"],
        )

    def peek_record(self, telegram_user_id: int) -> PendingMessageRecord | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT chat_id, team_id, message_id, role_name, content, reply_text FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["team_id"] is None:
            return None
        return {
            "chat_id": int(row["chat_id"]),
            "team_id": int(row["team_id"]),
            "message_id": int(row["message_id"]),
            "role_name": str(row["role_name"]),
            "content": str(row["content"]),
            "reply_text": row["reply_text"],
        }

    def clear_all(self) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM pending_messages")
        self._conn.commit()
