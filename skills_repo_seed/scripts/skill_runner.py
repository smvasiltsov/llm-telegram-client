#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_sdk.registry import SkillRegistry
from skills_sdk.contract import SkillContext


def _load_json_arg(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON value must be an object")
    return value


def _load_json_file(path: str | None) -> dict:
    if not path:
        return {}
    text = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON file {path} must contain object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local model-callable skill with mock context and arguments.")
    parser.add_argument("--skills-dir", default="skills", help="Path to skills directory.")
    parser.add_argument("--skill-id", required=True, help="Skill id from skill.yaml.")
    parser.add_argument("--arguments-json", default=None, help="Inline JSON object for skill arguments.")
    parser.add_argument("--arguments-file", default=None, help="Path to JSON file for skill arguments.")
    parser.add_argument("--config-json", default=None, help="Inline JSON object for skill config.")
    parser.add_argument("--config-file", default=None, help="Path to JSON file for skill config.")
    parser.add_argument("--chat-id", type=int, default=-1)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--role-id", type=int, default=1)
    parser.add_argument("--role-name", default="dev")
    args = parser.parse_args()

    registry = SkillRegistry()
    registry.discover(args.skills_dir)
    record = registry.get(args.skill_id)
    if record is None:
        print(
            json.dumps(
                {
                    "error": f"Skill '{args.skill_id}' not found",
                    "available": [spec.skill_id for spec in registry.list_specs()],
                },
                ensure_ascii=False,
            )
        )
        return 2

    arguments = _load_json_file(args.arguments_file)
    arguments.update(_load_json_arg(args.arguments_json))

    config = _load_json_file(args.config_file)
    config.update(_load_json_arg(args.config_json))

    config_errors = record.instance.validate_config(config)
    if config_errors:
        print(json.dumps({"status": "invalid_config", "errors": config_errors}, ensure_ascii=False, indent=2))
        return 3

    ctx = SkillContext(
        chain_id=uuid4().hex[:8],
        chat_id=args.chat_id,
        user_id=args.user_id,
        role_id=args.role_id,
        role_name=args.role_name,
    )
    result = record.instance.run(ctx, arguments, config)
    print(
        json.dumps(
            {
                "skill_id": record.spec.skill_id,
                "arguments": arguments,
                "config": config,
                "result": {
                    "ok": result.ok,
                    "output": result.output,
                    "error": result.error,
                    "metadata": result.metadata,
                },
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
