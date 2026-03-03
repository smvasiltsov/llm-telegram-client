from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_root_config(config: dict[str, Any]) -> list[str]:
    root_dir = config.get("root_dir")
    if not isinstance(root_dir, str) or not root_dir.strip():
        return ["config.root_dir is required"]
    root_path = Path(root_dir).expanduser()
    if not root_path.exists():
        return [f"config.root_dir does not exist: {root_path}"]
    if not root_path.is_dir():
        return [f"config.root_dir is not a directory: {root_path}"]
    return []


def resolve_root(config: dict[str, Any]) -> Path:
    return Path(str(config["root_dir"])).expanduser().resolve()


def resolve_target_path(root_dir: Path, relative_path: str) -> Path:
    raw_path = Path(relative_path)
    if raw_path.is_absolute():
        raise ValueError("path must be relative to the configured root_dir")
    target = (root_dir / raw_path).resolve()
    try:
        target.relative_to(root_dir)
    except ValueError as exc:
        raise ValueError("path escapes the configured root_dir") from exc
    return target


def clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return min(maximum, max(minimum, parsed))
