from __future__ import annotations

from typing import Any

from app.skills.contract import SkillContext, SkillResult, SkillSpec
from skills._fs_common import clamp_int, resolve_root, resolve_target_path, validate_root_config


DEFAULT_MAX_ENTRIES = 200


class FSListDirSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="fs.list_dir",
            name="List Directory",
            version="0.1.0",
            description="List directory entries within the allowed root_dir.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                },
            },
            mode="read_only",
            timeout_sec=15,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return validate_root_config(config)

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        path = arguments.get("path", ".")
        if not isinstance(path, str) or not path.strip():
            return SkillResult(ok=False, error="arguments.path must be a string when provided")

        root_dir = resolve_root(config)
        try:
            target = resolve_target_path(root_dir, path.strip())
        except ValueError as exc:
            return SkillResult(ok=False, error=str(exc))
        if not target.exists():
            return SkillResult(ok=False, error=f"Directory does not exist: {path}")
        if not target.is_dir():
            return SkillResult(ok=False, error=f"Path is not a directory: {path}")

        limit = clamp_int(arguments.get("limit"), default=DEFAULT_MAX_ENTRIES, minimum=1, maximum=1000)
        entries = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:limit]:
            relative_path = child.relative_to(root_dir).as_posix()
            entries.append(
                {
                    "path": relative_path,
                    "name": child.name,
                    "kind": "dir" if child.is_dir() else "file",
                    "size_bytes": child.stat().st_size if child.is_file() else None,
                }
            )

        return SkillResult(
            ok=True,
            output={
                "path": path.strip(),
                "entries": entries,
                "count": len(entries),
                "truncated": len(list(sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())))) > limit,
            },
        )


def create_skill() -> FSListDirSkill:
    return FSListDirSkill()
