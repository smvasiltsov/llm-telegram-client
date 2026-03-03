from __future__ import annotations

from typing import Any

from app.skills.contract import SkillContext, SkillResult, SkillSpec
from skills._fs_common import resolve_root, resolve_target_path, validate_root_config


class FSWriteFileSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="fs.write_file",
            name="Write File",
            version="0.1.0",
            description="Create, replace, or append UTF-8 text files within the allowed root_dir.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["replace", "append"]},
                    "create_dirs": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
            mode="mutating",
            timeout_sec=20,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return validate_root_config(config)

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        path = arguments.get("path")
        content = arguments.get("content")
        mode = arguments.get("mode", "replace")
        create_dirs = bool(arguments.get("create_dirs", False))

        if not isinstance(path, str) or not path.strip():
            return SkillResult(ok=False, error="arguments.path is required")
        if not isinstance(content, str):
            return SkillResult(ok=False, error="arguments.content must be a string")
        if mode not in {"replace", "append"}:
            return SkillResult(ok=False, error="arguments.mode must be 'replace' or 'append'")

        root_dir = resolve_root(config)
        try:
            target = resolve_target_path(root_dir, path.strip())
        except ValueError as exc:
            return SkillResult(ok=False, error=str(exc))

        parent = target.parent
        if not parent.exists():
            if not create_dirs:
                return SkillResult(ok=False, error=f"Parent directory does not exist: {parent.relative_to(root_dir).as_posix()}")
            parent.mkdir(parents=True, exist_ok=True)

        existed_before = target.exists()
        previous_size = target.stat().st_size if existed_before and target.is_file() else 0
        if existed_before and not target.is_file():
            return SkillResult(ok=False, error=f"Path is not a file: {path}")

        write_mode = "a" if mode == "append" else "w"
        with target.open(write_mode, encoding="utf-8") as fh:
            fh.write(content)

        size_after = target.stat().st_size
        return SkillResult(
            ok=True,
            output={
                "path": path.strip(),
                "mode": mode,
                "created": not existed_before,
                "appended": mode == "append",
                "bytes_written": len(content.encode("utf-8")),
                "previous_size_bytes": previous_size,
                "size_after_bytes": size_after,
            },
        )


def create_skill() -> FSWriteFileSkill:
    return FSWriteFileSkill()
