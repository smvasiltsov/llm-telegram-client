from __future__ import annotations

import re
from typing import Iterable


TELEGRAM_MESSAGE_LIMIT = 4096


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> Iterable[str]:
    if len(text) <= limit:
        yield text
        return

    paragraphs = text.split("\n\n")
    chunk = ""
    for para in paragraphs:
        candidate = para if not chunk else f"{chunk}\n\n{para}"
        if len(candidate) <= limit:
            chunk = candidate
            continue

        if chunk:
            yield chunk
            chunk = ""

        if len(para) <= limit:
            chunk = para
            continue

        for i in range(0, len(para), limit):
            yield para[i : i + limit]

    if chunk:
        yield chunk


def strip_bot_mention(text: str, bot_username: str) -> str:
    pattern = re.compile(rf"@{re.escape(bot_username)}", re.IGNORECASE)
    return pattern.sub("", text).strip()


def extract_role_mentions(text: str, roles: set[str]) -> list[str]:
    lowered = text.lower()
    found = []
    for role in roles:
        if f"@{role.lower()}" in lowered:
            found.append(role)
    return found
