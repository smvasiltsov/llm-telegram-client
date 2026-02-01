from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class BufferedMessage:
    chat_id: int
    message_id: int
    content: str
    reply_text: str | None
    created_at: datetime


class MessageBuffer:
    def __init__(self, window_seconds: float = 2.0) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._buffer: dict[tuple[int, int], list[BufferedMessage]] = {}
        self._scheduled: set[tuple[int, int]] = set()
        self._lock = asyncio.Lock()

    async def add(
        self,
        chat_id: int,
        user_id: int,
        message_id: int,
        content: str,
        start: bool,
        reply_text: str | None = None,
    ) -> bool:
        key = (chat_id, user_id)
        item = BufferedMessage(
            chat_id=chat_id,
            message_id=message_id,
            content=content,
            reply_text=reply_text,
            created_at=datetime.now(timezone.utc),
        )
        async with self._lock:
            existing = self._buffer.get(key)
            if existing:
                first_time = existing[0].created_at
                if item.created_at - first_time <= self._window:
                    existing.append(item)
                    return False
                self._buffer.pop(key, None)
                self._scheduled.discard(key)

            if not start:
                return False

            self._buffer[key] = [item]
            return True

    async def collect(self, chat_id: int, user_id: int) -> list[BufferedMessage]:
        key = (chat_id, user_id)
        async with self._lock:
            items = list(self._buffer.get(key, []))
            self._buffer.pop(key, None)
            self._scheduled.discard(key)
        return items

    async def wait_and_collect(self, chat_id: int, user_id: int) -> list[BufferedMessage]:
        await asyncio.sleep(self._window.total_seconds())
        return await self.collect(chat_id, user_id)

    async def mark_scheduled(self, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        async with self._lock:
            if key in self._scheduled:
                return False
            self._scheduled.add(key)
            return True
