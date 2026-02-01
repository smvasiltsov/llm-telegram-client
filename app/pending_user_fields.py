from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class PendingUserFieldStore:
    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_user_fields (
                telegram_user_id INTEGER PRIMARY KEY,
                provider_id TEXT NOT NULL,
                key TEXT NOT NULL,
                role_id INTEGER,
                prompt TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def save(
        self,
        telegram_user_id: int,
        provider_id: str,
        key: str,
        role_id: int | None,
        prompt: str,
        chat_id: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO pending_user_fields
                (telegram_user_id, provider_id, key, role_id, prompt, chat_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                provider_id=excluded.provider_id,
                key=excluded.key,
                role_id=excluded.role_id,
                prompt=excluded.prompt,
                chat_id=excluded.chat_id,
                created_at=excluded.created_at
            """,
            (telegram_user_id, provider_id, key, role_id, prompt, chat_id, now),
        )
        self._conn.commit()

    def get(self, telegram_user_id: int) -> dict[str, object] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT provider_id, key, role_id, prompt, chat_id
            FROM pending_user_fields
            WHERE telegram_user_id = ?
            """,
            (telegram_user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "provider_id": row["provider_id"],
            "key": row["key"],
            "role_id": row["role_id"],
            "prompt": row["prompt"],
            "chat_id": row["chat_id"],
        }

    def delete(self, telegram_user_id: int) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "DELETE FROM pending_user_fields WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        self._conn.commit()

