from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    database_path: str
    encryption_key: str
    llm_timeout_sec: int
    owner_user_id: int
    require_bot_mention: bool


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text())
    routing_raw = raw.get("routing", {})
    llm_raw = raw.get("llm", {})

    return AppConfig(
        telegram_bot_token=raw["telegram_bot_token"],
        database_path=raw.get("database_path", "./bot.sqlite3"),
        encryption_key=raw["encryption_key"],
        llm_timeout_sec=int(llm_raw.get("timeout_sec", 600)),
        owner_user_id=int(raw["owner_user_id"]),
        require_bot_mention=bool(routing_raw.get("require_bot_mention", True)),
    )
