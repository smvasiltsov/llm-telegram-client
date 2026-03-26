from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASH_SAFE_COMMANDS = [
    "pwd",
    "ls",
    "whoami",
    "date",
    "echo",
    "cat",
    "touch",
    "cp",
    "mkdir",
    "tee",
    "printf",
    "rg",
    "git",
    "python3",
]

DEFAULT_SKILLS_USAGE_PROMPT = (
    "You can call skills by answering with a JSON object with strict structure. "
    "If you do not want to use skills, answer normally and your answer will be sent to the user. "
    'When calling a skill, answer with exactly this JSON object: '
    '{"type":"skill_call","skill_call":{"skill_id":"<skill_id>","arguments":{...}}}. '
    "Use only skill ids from skills.available."
)
DEFAULT_SKILLS_FOLLOWUP_MODE = "full"
ALLOWED_SKILLS_FOLLOWUP_MODES = {"full", "compact"}
DEFAULT_TEAM_ROLLOUT_MODE = "legacy"
ALLOWED_TEAM_ROLLOUT_MODES = {"legacy", "shadow", "team"}
DEFAULT_INTERFACE_ACTIVE = "telegram"
DEFAULT_INTERFACE_MODULES_DIR = "app.interfaces"
DEFAULT_INTERFACE_RUNTIME_MODE = "single"
ALLOWED_INTERFACE_RUNTIME_MODES = {"single"}
DEFAULT_FREE_TRANSITION_DELAY_SEC = 0


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    database_path: str
    encryption_key: str
    llm_timeout_sec: int
    owner_user_id: int
    require_bot_mention: bool
    orchestrator_max_chain_auto_steps: int
    allow_raw_html: bool
    formatting_mode: str
    plugin_server_host: str
    plugin_server_port: int
    plugin_server_enabled: bool
    skills_usage_prompt: str
    skills_max_steps_per_request: int
    skills_followup_mode: str
    tools_enabled: bool
    tools_bash_enabled: bool
    tools_bash_default_cwd: str
    tools_bash_max_timeout_sec: int
    tools_bash_max_output_chars: int
    tools_bash_safe_commands: list[str]
    tools_bash_allowed_workdirs: list[str]
    team_dual_read_enabled: bool
    team_dual_write_enabled: bool
    team_rollout_mode: str
    interface_active: str
    interface_modules_dir: str
    interface_runtime_mode: str
    free_transition_delay_sec: int


def load_dotenv(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'"))):
            value = value[1:-1]
        result[key] = value
    return result


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text())
    routing_raw = raw.get("routing", {})
    orchestrator_raw = raw.get("orchestrator", {})
    llm_raw = raw.get("llm", {})
    formatting_raw = raw.get("formatting", {})
    plugin_server_raw = raw.get("plugin_server", {})
    skills_raw = raw.get("skills", {}) or {}
    tools_raw = raw.get("tools", {}) or {}
    bash_raw = tools_raw.get("bash", {}) or {}
    migration_raw = raw.get("migration", {}) or {}
    team_migration_raw = migration_raw.get("team", {}) or {}
    interface_raw = raw.get("interface", {}) or {}
    runtime_status_raw = raw.get("runtime_status", {}) or {}

    safe_commands_raw = bash_raw.get("safe_commands")
    if safe_commands_raw is None:
        safe_commands_raw = bash_raw.get("allowed_commands", DEFAULT_BASH_SAFE_COMMANDS)
    if not isinstance(safe_commands_raw, list):
        safe_commands_raw = []
    safe_commands = [str(item).strip() for item in safe_commands_raw if str(item).strip()]

    allowed_workdirs_raw = bash_raw.get("allowed_workdirs", [])
    if not isinstance(allowed_workdirs_raw, list):
        allowed_workdirs_raw = []
    allowed_workdirs = [str(item).strip() for item in allowed_workdirs_raw if str(item).strip()]

    skills_followup_mode = str(skills_raw.get("followup_mode", DEFAULT_SKILLS_FOLLOWUP_MODE)).strip().lower()
    if skills_followup_mode not in ALLOWED_SKILLS_FOLLOWUP_MODES:
        skills_followup_mode = DEFAULT_SKILLS_FOLLOWUP_MODE
    team_rollout_mode = str(team_migration_raw.get("rollout_mode", DEFAULT_TEAM_ROLLOUT_MODE)).strip().lower()
    if team_rollout_mode not in ALLOWED_TEAM_ROLLOUT_MODES:
        team_rollout_mode = DEFAULT_TEAM_ROLLOUT_MODE
    interface_runtime_mode = str(interface_raw.get("runtime_mode", DEFAULT_INTERFACE_RUNTIME_MODE)).strip().lower()
    if interface_runtime_mode not in ALLOWED_INTERFACE_RUNTIME_MODES:
        interface_runtime_mode = DEFAULT_INTERFACE_RUNTIME_MODE

    return AppConfig(
        telegram_bot_token=raw["telegram_bot_token"],
        database_path=raw.get("database_path", "./bot.sqlite3"),
        encryption_key=raw["encryption_key"],
        llm_timeout_sec=int(llm_raw.get("timeout_sec", 600)),
        owner_user_id=int(raw["owner_user_id"]),
        require_bot_mention=bool(routing_raw.get("require_bot_mention", True)),
        orchestrator_max_chain_auto_steps=int(
            raw.get(
                "orchestrator_max_chain_auto_steps",
                orchestrator_raw.get("max_chain_auto_steps", 30),
            )
        ),
        allow_raw_html=bool(formatting_raw.get("allow_raw_html", True)),
        formatting_mode=str(formatting_raw.get("mode", "html")).lower(),
        plugin_server_host=str(plugin_server_raw.get("host", "127.0.0.1")),
        plugin_server_port=int(plugin_server_raw.get("port", 8015)),
        plugin_server_enabled=bool(plugin_server_raw.get("enabled", True)),
        skills_usage_prompt=str(skills_raw.get("usage_prompt", DEFAULT_SKILLS_USAGE_PROMPT)).strip(),
        skills_max_steps_per_request=max(1, int(skills_raw.get("max_steps_per_request", 8))),
        skills_followup_mode=skills_followup_mode,
        tools_enabled=bool(tools_raw.get("enabled", True)),
        tools_bash_enabled=bool(bash_raw.get("enabled", True)),
        tools_bash_default_cwd=str(bash_raw.get("default_cwd", ".")),
        tools_bash_max_timeout_sec=int(bash_raw.get("max_timeout_sec", 30)),
        tools_bash_max_output_chars=int(bash_raw.get("max_output_chars", 12000)),
        tools_bash_safe_commands=safe_commands,
        tools_bash_allowed_workdirs=allowed_workdirs,
        team_dual_read_enabled=bool(team_migration_raw.get("dual_read_enabled", False)),
        team_dual_write_enabled=bool(team_migration_raw.get("dual_write_enabled", False)),
        team_rollout_mode=team_rollout_mode,
        interface_active=str(interface_raw.get("active", DEFAULT_INTERFACE_ACTIVE)).strip().lower() or DEFAULT_INTERFACE_ACTIVE,
        interface_modules_dir=str(interface_raw.get("modules_dir", DEFAULT_INTERFACE_MODULES_DIR)).strip()
        or DEFAULT_INTERFACE_MODULES_DIR,
        interface_runtime_mode=interface_runtime_mode,
        free_transition_delay_sec=max(0, int(runtime_status_raw.get("free_transition_delay_sec", DEFAULT_FREE_TRANSITION_DELAY_SEC))),
    )
