from __future__ import annotations

from typing import Any

from app.skills.contract import SkillContext, SkillResult, SkillSpec
from skills._fs_common import clamp_int, resolve_root, resolve_target_path, validate_root_config


DEFAULT_MAX_CHARS = 12000


class FSReadFileSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="fs.read_file",
            name="Read File",
            version="0.1.0",
            description="Read a text file within the allowed root_dir by character range.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_char": {"type": "integer", "minimum": 0},
                    "end_char": {"type": "integer", "minimum": 0},
                },
                "required": ["path"],
            },
            mode="read_only",
            timeout_sec=15,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return validate_root_config(config)

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            return SkillResult(ok=False, error="arguments.path is required")

        root_dir = resolve_root(config)
        try:
            target = resolve_target_path(root_dir, path.strip())
        except ValueError as exc:
            return SkillResult(ok=False, error=str(exc))
        if not target.exists():
            return SkillResult(ok=False, error=f"File does not exist: {path}")
        if not target.is_file():
            return SkillResult(ok=False, error=f"Path is not a file: {path}")

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return SkillResult(ok=False, error=f"File is not valid UTF-8 text: {path}")

        max_chars = clamp_int(config.get("max_read_chars"), default=DEFAULT_MAX_CHARS, minimum=1, maximum=200000)
        total_chars = len(text)
        start_char = clamp_int(arguments.get("start_char"), default=0, minimum=0, maximum=total_chars)
        if "end_char" in arguments and arguments.get("end_char") is not None:
            end_char = clamp_int(arguments.get("end_char"), default=total_chars, minimum=0, maximum=total_chars)
        else:
            end_char = min(total_chars, start_char + max_chars)
        if end_char < start_char:
            return SkillResult(ok=False, error="arguments.end_char must be greater than or equal to start_char")
        if end_char - start_char > max_chars:
            end_char = start_char + max_chars

        content = text[start_char:end_char]
        return SkillResult(
            ok=True,
            output={
                "path": path.strip(),
                "start_char": start_char,
                "end_char": end_char,
                "content": content,
                "chars_read": len(content),
                "total_chars": total_chars,
                "truncated": end_char < total_chars,
            },
        )


def create_skill() -> FSReadFileSkill:
    return FSReadFileSkill()
