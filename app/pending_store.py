from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO pending_messages (telegram_user_id, chat_id, message_id, role_name, content, reply_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id=excluded.chat_id,
                message_id=excluded.message_id,
                role_name=excluded.role_name,
                content=excluded.content,
                reply_text=excluded.reply_text,
                created_at=excluded.created_at
            """,
            (telegram_user_id, chat_id, message_id, role_name, content, reply_text, now),
        )
        self._conn.commit()

    def pop(self, telegram_user_id: int) -> tuple[int, int, str, str, str | None] | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT chat_id, message_id, role_name, content, reply_text FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "DELETE FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        self._conn.commit()
        return (row["chat_id"], row["message_id"], row["role_name"], row["content"], row["reply_text"])

    def peek(self, telegram_user_id: int) -> tuple[int, int, str, str, str | None] | None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT chat_id, message_id, role_name, content, reply_text FROM pending_messages WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return (row["chat_id"], row["message_id"], row["role_name"], row["content"], row["reply_text"])
