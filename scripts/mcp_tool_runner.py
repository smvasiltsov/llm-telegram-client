#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config, load_dotenv
from app.tools import BashTool, ToolMCPAdapter, ToolRegistry, ToolService


def _load_json_arg(raw: str | None, *, field_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {field_name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _load_json_file(path: str | None, *, field_name: str) -> dict[str, Any]:
    if not path:
        return {}
    text = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file for {field_name} ({path}): {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} file must contain a JSON object")
    return value


def _resolve_allowed_workdirs(raw: list[str], base_cwd: Path) -> list[Path]:
    resolved: list[Path] = []
    for item in raw:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = (base_cwd / path).resolve()
        else:
            path = path.resolve()
        resolved.append(path)
    return resolved


def _build_mcp_adapter(config_path: Path, dotenv_path: Path) -> tuple[ToolMCPAdapter, int]:
    config = load_config(config_path)
    _ = load_dotenv(dotenv_path)
    base_cwd = PROJECT_ROOT

    tool_registry = ToolRegistry()
    tools_bash_enabled = bool(config.tools_enabled and config.tools_bash_enabled)
    if tools_bash_enabled:
        default_cwd = Path(config.tools_bash_default_cwd).expanduser()
        if not default_cwd.is_absolute():
            default_cwd = (base_cwd / default_cwd).resolve()
        else:
            default_cwd = default_cwd.resolve()
        allowed_workdirs = _resolve_allowed_workdirs(config.tools_bash_allowed_workdirs, base_cwd)
        tool_registry.register(
            BashTool(
                default_cwd=default_cwd,
                max_timeout_sec=config.tools_bash_max_timeout_sec,
                max_output_chars=config.tools_bash_max_output_chars,
                safe_commands=config.tools_bash_safe_commands,
                allowed_workdirs=allowed_workdirs or [default_cwd],
            )
        )
    tool_service = ToolService(tool_registry)
    return ToolMCPAdapter(tool_service), int(config.owner_user_id)


async def _run_exec(
    adapter: ToolMCPAdapter,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    caller_id: int,
    owner_user_id: int,
    chat_id: int,
    request_id: str | None,
) -> dict[str, Any]:
    return await adapter.execute_tool(
        tool_name=tool_name,
        tool_input=tool_input,
        caller_id=caller_id,
        owner_user_id=owner_user_id,
        chat_id=chat_id,
        request_id=request_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tool MCP adapter commands directly from terminal.")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--dotenv", default=".env", help="Path to .env")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    list_parser = subparsers.add_parser("list", help="List tools visible to caller")
    list_parser.add_argument("--caller-id", type=int, required=True)

    exec_parser = subparsers.add_parser("exec", help="Execute tool through MCP adapter")
    exec_parser.add_argument("--caller-id", type=int, required=True)
    exec_parser.add_argument("--chat-id", type=int, default=0)
    exec_parser.add_argument("--tool-name", required=True)
    exec_parser.add_argument("--tool-input-json", default=None)
    exec_parser.add_argument("--tool-input-file", default=None)
    exec_parser.add_argument("--request-id", default=None)

    args = parser.parse_args()
    adapter, owner_user_id = _build_mcp_adapter(Path(args.config), Path(args.dotenv))

    if args.cmd == "list":
        result = {
            "owner_user_id": owner_user_id,
            "caller_id": int(args.caller_id),
            "tools": adapter.list_tools(caller_id=int(args.caller_id), owner_user_id=owner_user_id),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    tool_input = _load_json_file(args.tool_input_file, field_name="tool_input")
    tool_input.update(_load_json_arg(args.tool_input_json, field_name="tool_input"))
    request_id = str(args.request_id).strip() if args.request_id else uuid4().hex[:8]
    result = asyncio.run(
        _run_exec(
            adapter,
            tool_name=str(args.tool_name),
            tool_input=tool_input,
            caller_id=int(args.caller_id),
            owner_user_id=owner_user_id,
            chat_id=int(args.chat_id),
            request_id=request_id,
        )
    )
    print(
        json.dumps(
            {
                "owner_user_id": owner_user_id,
                "caller_id": int(args.caller_id),
                "tool_name": str(args.tool_name),
                "request_id": request_id,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
