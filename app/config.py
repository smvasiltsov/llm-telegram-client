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
    allow_raw_html: bool
    formatting_mode: str
    plugin_server_host: str
    plugin_server_port: int
    plugin_server_enabled: bool


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text())
    routing_raw = raw.get("routing", {})
    llm_raw = raw.get("llm", {})
    formatting_raw = raw.get("formatting", {})
    plugin_server_raw = raw.get("plugin_server", {})

    return AppConfig(
        telegram_bot_token=raw["telegram_bot_token"],
        database_path=raw.get("database_path", "./bot.sqlite3"),
        encryption_key=raw["encryption_key"],
        llm_timeout_sec=int(llm_raw.get("timeout_sec", 600)),
        owner_user_id=int(raw["owner_user_id"]),
        require_bot_mention=bool(routing_raw.get("require_bot_mention", True)),
        allow_raw_html=bool(formatting_raw.get("allow_raw_html", True)),
        formatting_mode=str(formatting_raw.get("mode", "html")).lower(),
        plugin_server_host=str(plugin_server_raw.get("host", "127.0.0.1")),
        plugin_server_port=int(plugin_server_raw.get("port", 8015)),
        plugin_server_enabled=bool(plugin_server_raw.get("enabled", True)),
    )
