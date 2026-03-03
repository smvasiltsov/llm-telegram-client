from __future__ import annotations

import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from prepost_processing_sdk.contract import (
    PrePostProcessingContext,
    PrePostProcessingResult,
    PrePostProcessingSpec,
)


SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9._/@%+=:,\-]+$")


def _ensure_int(value: Any, field: str, min_value: int, max_value: int) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(f"{field} must be in range {min_value}..{max_value}")
    return value


def _resolve_root(root_dir: Any) -> Path:
    if not isinstance(root_dir, str) or not root_dir.strip():
        raise ValueError("root_dir is required and must be a non-empty string")
    root = Path(root_dir).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root_dir must point to an existing directory")
    return root


def _validate_allowed_commands(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("allowed_commands is required and must be a non-empty list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError("allowed_commands is required and must be a non-empty list of strings")
        if "/" in item or "\\" in item or not SAFE_TOKEN_RE.fullmatch(item):
            raise ValueError("allowed_commands entries must be simple command names")
        out.append(item)
    return out


def _resolve_inside_root(root: Path, rel_path: Any) -> Path:
    if not isinstance(rel_path, str):
        raise ValueError("cwd must be a string")
    normalized = rel_path.strip() or "."
    raw = Path(normalized)
    if raw.is_absolute():
        raise ValueError("cwd must be relative")
    if normalized.startswith("../") or "/../" in f"/{normalized}" or normalized == "..":
        raise ValueError("cwd traversal is not allowed")
    target = (root / raw).resolve(strict=True)
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError("cwd escapes root_dir")
    if not target.is_dir():
        raise ValueError("cwd must be a directory")
    return target


def _load_data(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    data = payload.get("data")
    if data is None:
        return payload
    if not isinstance(data, dict):
        raise ValueError("payload.data must be an object")
    return data


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


@lru_cache(maxsize=1)
def _read_default_config() -> dict[str, Any]:
    path = Path(__file__).with_name("config.json")
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config.json must contain an object")
    return raw


def _merge_config(override: Any) -> dict[str, Any]:
    defaults = _read_default_config()
    if override is None:
        override_obj: dict[str, Any] = {}
    elif isinstance(override, dict):
        override_obj = override
    else:
        raise ValueError("config must be an object")
    return {**defaults, **override_obj}


class ExecPrePostProcessing:
    def describe(self) -> PrePostProcessingSpec:
        return PrePostProcessingSpec(
            prepost_processing_id="exec-processing",
            name="Exec Pre/Post Processing",
            version="0.1.0",
            description="Runs only whitelisted commands inside configured root_dir.",
            permissions=(),
            timeout_sec=20,
        )

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []
        try:
            merged = _merge_config(config)
        except ValueError as exc:
            return [str(exc)]
        try:
            _resolve_root(merged.get("root_dir"))
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
        try:
            _validate_allowed_commands(merged.get("allowed_commands"))
        except ValueError as exc:
            errors.append(str(exc))
        max_output_chars = merged.get("max_output_chars", 2000)
        default_timeout_sec = merged.get("default_timeout_sec", 5)
        max_args = merged.get("max_args", 16)
        try:
            _ensure_int(max_output_chars, "max_output_chars", 64, 12_000)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _ensure_int(default_timeout_sec, "default_timeout_sec", 1, 30)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _ensure_int(max_args, "max_args", 0, 64)
        except ValueError as exc:
            errors.append(str(exc))
        return errors

    def run(self, ctx: PrePostProcessingContext, payload: dict) -> PrePostProcessingResult:
        _ = ctx
        try:
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            config = _merge_config(payload.get("config", {}))
            root = _resolve_root(config.get("root_dir"))
            allowed_commands = set(_validate_allowed_commands(config.get("allowed_commands")))
            max_output_chars = _ensure_int(config.get("max_output_chars", 2000), "max_output_chars", 64, 12_000)
            default_timeout_sec = _ensure_int(config.get("default_timeout_sec", 5), "default_timeout_sec", 1, 30)
            max_args = _ensure_int(config.get("max_args", 16), "max_args", 0, 64)
            data = _load_data(payload)

            operation = data.get("operation", "exec")
            if operation != "exec":
                raise ValueError("unsupported operation")
            command = data.get("command")
            if not isinstance(command, str) or not command:
                raise ValueError("command is required and must be a string")
            if command not in allowed_commands:
                raise ValueError("command is not allowed")
            if "/" in command or "\\" in command or not SAFE_TOKEN_RE.fullmatch(command):
                raise ValueError("command format is not allowed")

            raw_args = data.get("args", [])
            if not isinstance(raw_args, list):
                raise ValueError("args must be an array of strings")
            if len(raw_args) > max_args:
                raise ValueError("args length exceeds max_args")
            args: list[str] = []
            for item in raw_args:
                if not isinstance(item, str) or not SAFE_TOKEN_RE.fullmatch(item):
                    raise ValueError("args must contain only safe string tokens")
                args.append(item)

            cwd = _resolve_inside_root(root, data.get("cwd", "."))
            timeout_sec = _ensure_int(data.get("timeout_sec", default_timeout_sec), "timeout_sec", 1, 30)

            proc = subprocess.run(
                [command, *args],
                cwd=str(cwd),
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            stdout, stdout_truncated = _truncate(proc.stdout, max_output_chars)
            stderr, stderr_truncated = _truncate(proc.stderr, max_output_chars)
            return PrePostProcessingResult(
                status="ok",
                output={
                    "operation": "exec",
                    "command": command,
                    "args": args,
                    "cwd": str(cwd.relative_to(root)) or ".",
                    "returncode": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                },
            )
        except subprocess.TimeoutExpired:
            return PrePostProcessingResult(status="error", error="command timed out", output={}, metadata={})
        except Exception as exc:
            return PrePostProcessingResult(status="error", error=str(exc), output={}, metadata={})


def create_processor() -> ExecPrePostProcessing:
    return ExecPrePostProcessing()
