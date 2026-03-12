#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_sdk.registry import SkillRegistry

DEFAULT_SKILLS_USAGE_PROMPT = (
    "You can call skills by answering with a JSON object with strict structure. "
    "If you do not want to use skills, answer normally and your answer will be sent to the user. "
    'When calling a skill, answer with exactly this JSON object: '
    '{"type":"skill_call","skill_call":{"skill_id":"<skill_id>","arguments":{...}}}. '
    "Use only skill ids from skills.available."
)

_EMPTY = object()


def _load_json_arg(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def _load_json_file(path: str | None) -> Any:
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Failed to read JSON file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON file {path}: {exc}") from exc


def _prune_empty(value: Any) -> Any:
    if value is None:
        return _EMPTY
    if value is False:
        return _EMPTY
    if isinstance(value, str):
        return value if value != "" else _EMPTY
    if isinstance(value, list):
        cleaned = [_prune_empty(item) for item in value]
        cleaned = [item for item in cleaned if item is not _EMPTY]
        return cleaned if cleaned else _EMPTY
    if isinstance(value, dict):
        cleaned = {
            key: item
            for key, item in ((k, _prune_empty(v)) for k, v in value.items())
            if item is not _EMPTY
        }
        return cleaned or _EMPTY
    return value


def _normalize_history(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("skills history must be a JSON array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each history item must be a JSON object")
        result.append(item)
    return result


def _normalize_enabled(value: Any) -> set[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("enabled skills must be a JSON array")
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("enabled skill ids must be non-empty strings")
        result.add(item.strip())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview the skills payload exactly as LLM sees it (skills.prompt + skills.available + contracts)."
    )
    parser.add_argument("--skills-dir", default="skills", help="Path to skills directory.")
    parser.add_argument("--skills-usage-prompt", default=DEFAULT_SKILLS_USAGE_PROMPT)
    parser.add_argument("--enabled-skill-id", action="append", default=[], help="Repeatable skill id filter.")
    parser.add_argument("--enabled-skills-json", default=None, help="JSON array of enabled skill ids.")
    parser.add_argument("--enabled-skills-file", default=None, help="Path to JSON file with enabled skill ids.")
    parser.add_argument("--history-json", default=None, help="JSON array for skills.history.")
    parser.add_argument("--history-file", default=None, help="Path to JSON file for skills.history.")
    parser.add_argument("--user-text", default="Demo request")
    parser.add_argument("--recipient", default="role")
    parser.add_argument("--trigger-type", default="mention_role")
    parser.add_argument("--mentioned-roles-json", default='["role"]')
    parser.add_argument(
        "--include-debug-meta",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include manifest/version/config hints for each skill.",
    )
    parser.add_argument(
        "--include-readme",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Include README excerpt for each skill when available.",
    )
    parser.add_argument("--readme-max-chars", type=int, default=1000, help="Max chars for README excerpt.")
    parser.add_argument("--output", choices=["skills_only", "input_json", "input_json_compact"], default="input_json")
    args = parser.parse_args()

    enabled_from_file = _normalize_enabled(_load_json_file(args.enabled_skills_file))
    enabled_from_json = _normalize_enabled(_load_json_arg(args.enabled_skills_json))
    enabled_from_cli = {item.strip() for item in args.enabled_skill_id if item.strip()}
    enabled_filter: set[str] | None = None
    for candidate in (enabled_from_file, enabled_from_json, enabled_from_cli or None):
        if candidate is None:
            continue
        enabled_filter = (enabled_filter or set()) | candidate

    history_value = _load_json_file(args.history_file)
    if history_value is None:
        history_value = _load_json_arg(args.history_json)
    history = _normalize_history(history_value)

    mentioned_roles = _load_json_arg(args.mentioned_roles_json)
    if not isinstance(mentioned_roles, list) or any(not isinstance(item, str) for item in mentioned_roles):
        raise ValueError("--mentioned-roles-json must be a JSON array of strings")

    registry = SkillRegistry()
    registry.discover(args.skills_dir)
    skills_root = Path(args.skills_dir).resolve()

    available: list[dict[str, Any]] = []
    for spec in sorted(registry.list_specs(), key=lambda item: item.skill_id):
        if enabled_filter is not None and spec.skill_id not in enabled_filter:
            continue
        item: dict[str, Any] = {
            "skill_id": spec.skill_id,
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "mode": spec.mode,
        }
        record = registry.get(spec.skill_id)
        if args.include_debug_meta and record is not None:
            config_empty_errors: list[str] = []
            try:
                config_empty_errors = [str(err) for err in record.instance.validate_config({})]
            except Exception as exc:
                config_empty_errors = [f"validate_config probe failed: {exc}"]
            item["debug"] = {
                "version": spec.version,
                "timeout_sec": spec.timeout_sec,
                "permissions": list(spec.permissions),
                "manifest": {
                    "id": str(record.manifest.get("id", "")),
                    "version": str(record.manifest.get("version", "")),
                    "entrypoint": str(record.manifest.get("entrypoint", "")),
                },
                "config_contract_hints": {
                    "validate_config_errors_for_empty_config": config_empty_errors,
                },
            }
        if args.include_readme and record is not None:
            folder = skills_root / str(record.manifest.get("id", "")).replace(".", "_")
            # skill folder name may differ from manifest id; fallback to skill_id folder.
            candidates = [
                skills_root / spec.skill_id.replace(".", "_"),
                skills_root / spec.skill_id.replace(".", "-"),
                skills_root / spec.skill_id,
                folder,
            ]
            readme_text: str | None = None
            for candidate in candidates:
                for name in ("README.md", "readme.md", "README.MD"):
                    path = candidate / name
                    if path.exists() and path.is_file():
                        try:
                            readme_text = path.read_text(encoding="utf-8")
                        except OSError:
                            readme_text = None
                        break
                if readme_text:
                    break
            if readme_text:
                readme_excerpt = " ".join(readme_text.split())
                item["readme_excerpt"] = readme_excerpt[: max(0, args.readme_max_chars)]
        available.append(item)

    skills_obj = {
        "prompt": args.skills_usage_prompt.strip() or None,
        "available": available,
        "history": history,
    }

    payload = {
        "actor": {"username": "user"},
        "instruction": {"system": None, "message": None, "reply": None},
        "context": {
            "routing": {
                "trigger_type": args.trigger_type,
                "mentioned_roles": mentioned_roles,
            },
            "reply": {"is_reply": False, "previous_message": None},
        },
        "user_request": {"text": args.user_text, "recipient": args.recipient},
        "llm_answer": {"text": None, "role_name": None},
        "skills": skills_obj,
    }
    compact_payload = _prune_empty(payload)
    if compact_payload is _EMPTY or not isinstance(compact_payload, dict):
        compact_payload = {}

    if args.output == "skills_only":
        print(json.dumps(skills_obj, ensure_ascii=False, indent=2))
        return 0
    if args.output == "input_json_compact":
        print("INPUT_JSON:")
        print(json.dumps(compact_payload, ensure_ascii=False))
        return 0
    print("INPUT_JSON:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
