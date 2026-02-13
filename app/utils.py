from __future__ import annotations

import re
from typing import Iterable


TELEGRAM_MESSAGE_LIMIT = 4096


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> Iterable[str]:
    if len(text) <= limit:
        yield text
        return

    code_pattern = re.compile(r"```(?:[^\n]*)\n?.*?```", re.S)
    matches = list(code_pattern.finditer(text))
    if not matches:
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
        return

    segments: list[str] = []
    cursor = 0
    for match in matches:
        if match.start() > cursor:
            segments.append(text[cursor:match.start()])
        segments.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        segments.append(text[cursor:])

    chunk = ""
    for segment in segments:
        if not segment:
            continue
        candidate = f"{chunk}{segment}" if chunk else segment
        if len(candidate) <= limit:
            chunk = candidate
            continue

        if chunk:
            yield chunk
            chunk = ""

        if len(segment) <= limit:
            chunk = segment
            continue

        for i in range(0, len(segment), limit):
            yield segment[i : i + limit]

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
    found.sort(key=len, reverse=True)
    return found
