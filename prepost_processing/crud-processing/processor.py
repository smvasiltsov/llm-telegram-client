from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any

from prepost_processing_sdk.contract import (
    PrePostProcessingContext,
    PrePostProcessingResult,
    PrePostProcessingSpec,
)


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_DIFF_MODES = ("strict", "autofix")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


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


def _resolve_inside_root(root: Path, rel_path: Any, *, allow_dot: bool = False, strict: bool = False) -> tuple[Path, str]:
    if not isinstance(rel_path, str):
        raise ValueError("path must be a string")
    normalized = rel_path.strip()
    if not normalized:
        raise ValueError("path must be non-empty")
    if normalized == "." and allow_dot:
        target = root
    else:
        raw = Path(normalized)
        if raw.is_absolute():
            raise ValueError("path must be relative")
        if normalized.startswith("../") or "/../" in f"/{normalized}" or normalized == "..":
            raise ValueError("path traversal is not allowed")
        target = (root / raw).resolve(strict=strict)
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError("path escapes root_dir")
    return target, normalized


def _load_data(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    data = payload.get("data")
    if data is None:
        return payload
    if not isinstance(data, dict):
        raise ValueError("payload.data must be an object")
    return data


def _ensure_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _ensure_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{field} must be non-empty")
    return value


def _normalize_diff_header_path(value: str) -> str:
    out = value.strip()
    for prefix in ("a/", "b/"):
        if out.startswith(prefix):
            out = out[len(prefix) :]
    return out


def _parse_hunk_header(line: str) -> tuple[int, int, int, int]:
    match = HUNK_HEADER_RE.match(line)
    if match is None:
        raise ValueError("invalid hunk header format")
    old_start = int(match.group(1))
    old_count = int(match.group(2)) if match.group(2) is not None else 1
    new_start = int(match.group(3))
    new_count = int(match.group(4)) if match.group(4) is not None else 1
    return old_start, old_count, new_start, new_count


def _count_hunk_body_lines(hunk_lines: list[str]) -> tuple[int, int]:
    old_seen = 0
    new_seen = 0
    for body in hunk_lines:
        if body == r"\ No newline at end of file":
            continue
        prefix = body[0]
        if prefix == " ":
            old_seen += 1
            new_seen += 1
        elif prefix == "-":
            old_seen += 1
        elif prefix == "+":
            new_seen += 1
    return old_seen, new_seen


def _split_hunk_lines(hunk_lines: list[str]) -> dict[str, list[str]]:
    first_change: int | None = None
    last_change: int | None = None
    for idx, body in enumerate(hunk_lines):
        if body == r"\ No newline at end of file":
            continue
        if body[0] in ("-", "+"):
            if first_change is None:
                first_change = idx
            last_change = idx

    context_before: list[str] = []
    context_after: list[str] = []
    deletions: list[str] = []
    insertions: list[str] = []
    for idx, body in enumerate(hunk_lines):
        if body == r"\ No newline at end of file":
            continue
        prefix = body[0]
        value = body[1:]
        if prefix == " ":
            if first_change is None or idx < first_change:
                context_before.append(value)
            elif last_change is not None and idx > last_change:
                context_after.append(value)
        elif prefix == "-":
            deletions.append(value)
        elif prefix == "+":
            insertions.append(value)
    return {
        "context_before": context_before,
        "deletions": deletions,
        "insertions": insertions,
        "context_after": context_after,
    }


def _parse_unified_diff(
    diff_text: str, normalized_path: str, max_diff_lines: int, *, tolerant: bool = False
) -> dict[str, Any]:
    if "\x00" in diff_text:
        raise ValueError("diff_text must not contain null bytes")
    lines = diff_text.splitlines()
    if len(lines) > max_diff_lines:
        raise ValueError("diff_text exceeds max_diff_lines")
    if any(token in diff_text for token in ("GIT binary patch", "Binary files ")):
        raise ValueError("binary diff is not supported")

    src_indices = [idx for idx, line in enumerate(lines) if line.startswith("--- ")]
    dst_indices = [idx for idx, line in enumerate(lines) if line.startswith("+++ ")]
    if len(src_indices) != 1 or len(dst_indices) != 1:
        raise ValueError("single-file unified diff must contain exactly one --- and one +++ header")
    src_idx = src_indices[0]
    dst_idx = dst_indices[0]
    if dst_idx != src_idx + 1:
        raise ValueError("+++ header must follow --- header")
    has_hunk = any(line.startswith("@@") for line in lines[dst_idx + 1 :])
    if not has_hunk:
        raise ValueError("diff_text must be unified diff with ---/+++ headers and @@ hunks")

    src_line = lines[src_idx]
    dst_line = lines[dst_idx]
    src_path = _normalize_diff_header_path(src_line[4:])
    dst_path = _normalize_diff_header_path(dst_line[4:])
    if src_path != normalized_path:
        raise ValueError("diff source header path must match payload.path")
    if dst_path != normalized_path:
        raise ValueError("diff target header path must match payload.path")

    idx = dst_idx + 1
    hunk_count = 0
    hunks: list[dict[str, Any]] = []
    force_no_trailing_newline: bool | None = None
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("@@"):
            old_start, old_count, new_start, new_count = _parse_hunk_header(line)
            if old_start < 0 or old_count < 0 or new_start < 0 or new_count < 0:
                raise ValueError("invalid hunk header values")
            idx += 1
            hunk_lines: list[str] = []
            prev_prefix: str | None = None
            while idx < len(lines) and not lines[idx].startswith("@@"):
                body = lines[idx]
                if body.startswith("--- ") or body.startswith("+++ "):
                    raise ValueError("multi-file diff is not supported")
                if body == r"\ No newline at end of file":
                    if prev_prefix == "+":
                        force_no_trailing_newline = True
                    hunk_lines.append(body)
                    idx += 1
                    continue
                if not body:
                    raise ValueError("invalid hunk line prefix")
                prefix = body[0]
                if prefix not in (" ", "-", "+"):
                    raise ValueError("invalid hunk line prefix")
                prev_prefix = prefix
                hunk_lines.append(body)
                idx += 1
            actual_old_count, actual_new_count = _count_hunk_body_lines(hunk_lines)
            has_count_mismatch = actual_old_count != old_count or actual_new_count != new_count
            if has_count_mismatch and not tolerant:
                raise ValueError("hunk line counts do not match hunk header")
            segments = _split_hunk_lines(hunk_lines)
            hunks.append(
                {
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                    "header_old_start": old_start,
                    "header_old_count": old_count,
                    "header_new_start": new_start,
                    "header_new_count": new_count,
                    "actual_old_count": actual_old_count,
                    "actual_new_count": actual_new_count,
                    "has_count_mismatch": has_count_mismatch,
                    "hunk_index": hunk_count,
                    "context_before": segments["context_before"],
                    "deletions": segments["deletions"],
                    "insertions": segments["insertions"],
                    "context_after": segments["context_after"],
                    "lines": hunk_lines,
                }
            )
            hunk_count += 1
            continue

        if hunk_count == 0 and (
            line.startswith("diff --git ")
            or line.startswith("index ")
            or line.startswith("old mode ")
            or line.startswith("new mode ")
            or line.startswith("new file mode ")
            or line.startswith("deleted file mode ")
        ):
            idx += 1
            continue
        raise ValueError("unexpected line outside hunk body")

    if hunk_count == 0:
        raise ValueError("diff must contain at least one hunk")
    return {
        "hunk_count": hunk_count,
        "line_count": len(lines),
        "hunks": hunks,
        "force_no_trailing_newline": force_no_trailing_newline,
    }


def _hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read_file_bytes(path: Path) -> bytes:
    if not path.exists():
        return b""
    return path.read_bytes()


def _autofix_diff_text(raw_diff_text: str) -> tuple[str, bool]:
    normalized = raw_diff_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    had_trailing_newline = normalized.endswith("\n")
    changed = normalized != raw_diff_text
    out_lines: list[str] = []
    for line in lines:
        if line.strip() == r"\ No newline at end of file":
            out_lines.append(r"\ No newline at end of file")
            if line != r"\ No newline at end of file":
                changed = True
            continue
        out_lines.append(line)
    fixed = "\n".join(out_lines)
    if had_trailing_newline:
        fixed += "\n"
    return fixed, changed


def _count_useful_context_chars(lines: list[str]) -> int:
    return sum(len("".join(part for part in line if not part.isspace())) for line in lines)


def _match_hunk_context_at(original_lines: list[str], start_idx: int, hunk: dict[str, Any]) -> dict[str, Any] | None:
    context_before = list(hunk["context_before"])
    context_after = list(hunk["context_after"])
    deletions = list(hunk["deletions"])
    before_len = len(context_before)
    after_len = len(context_after)
    delete_len = len(deletions)

    if start_idx < 0:
        return None
    if start_idx + before_len + delete_len + after_len > len(original_lines):
        return None

    if before_len and original_lines[start_idx : start_idx + before_len] != context_before:
        return None

    delete_start = start_idx + before_len
    delete_end = delete_start + delete_len
    if after_len and original_lines[delete_end : delete_end + after_len] != context_after:
        return None

    deletions_match = original_lines[delete_start:delete_end] == deletions
    context_lines = before_len + after_len
    context_chars = _count_useful_context_chars(context_before) + _count_useful_context_chars(context_after)
    matched_old_count = before_len + delete_len + after_len
    header_start = int(hunk["header_old_start"])
    header_idx = 0 if header_start == 0 else header_start - 1
    header_delta = start_idx - header_idx
    return {
        "start_idx": start_idx,
        "insertion_idx": delete_start,
        "matched_old_count": matched_old_count,
        "deletions_match": deletions_match,
        "context_lines": context_lines,
        "context_chars": context_chars,
        "header_delta": header_delta,
        "distance": abs(header_delta),
    }


def _choose_hunk_candidate(original_lines: list[str], hunk: dict[str, Any], *, min_start_idx: int = 0) -> dict[str, Any]:
    context_before = list(hunk["context_before"])
    context_after = list(hunk["context_after"])
    context_chars = _count_useful_context_chars(context_before) + _count_useful_context_chars(context_after)
    if context_chars < 15:
        return {
            "matched": False,
            "ambiguous": False,
            "reason": "insufficient_context",
            "match_strategy": "exact_context",
            "candidate_count": 0,
            "top_candidate_count": 0,
            "header_old_start": int(hunk["header_old_start"]),
        }

    candidates: list[dict[str, Any]] = []
    max_start = len(original_lines) - (len(hunk["context_before"]) + len(hunk["deletions"]) + len(hunk["context_after"]))
    for start_idx in range(max(min_start_idx, 0), max_start + 1):
        candidate = _match_hunk_context_at(original_lines, start_idx, hunk)
        if candidate is None:
            continue
        candidates.append(candidate)

    if not candidates:
        return {
            "matched": False,
            "ambiguous": False,
            "reason": "no_context_match",
            "match_strategy": "exact_context",
            "candidate_count": 0,
            "top_candidate_count": 0,
            "header_old_start": int(hunk["header_old_start"]),
        }

    ranked = sorted(
        candidates,
        key=lambda item: (
            item["context_lines"],
            item["context_chars"],
            1 if item["deletions_match"] else 0,
            -item["distance"],
        ),
        reverse=True,
    )
    best = ranked[0]
    best_key = (
        best["context_lines"],
        best["context_chars"],
        best["deletions_match"],
        best["distance"],
    )
    top_candidates = [
        item
        for item in ranked
        if (
            item["context_lines"],
            item["context_chars"],
            item["deletions_match"],
            item["distance"],
        )
        == best_key
    ]
    if len(top_candidates) != 1:
        return {
            "matched": False,
            "ambiguous": True,
            "reason": "ambiguous_context_match",
            "match_strategy": "exact_context",
            "candidate_count": len(candidates),
            "top_candidate_count": len(top_candidates),
            "header_old_start": int(hunk["header_old_start"]),
            "context_lines_used": best["context_lines"],
            "context_chars_used": best["context_chars"],
        }

    return {
        "matched": True,
        "ambiguous": False,
        "reason": None,
        "match_strategy": "exact_context",
        "candidate_count": len(candidates),
        "top_candidate_count": 1,
        "matched_start_idx": best["start_idx"],
        "matched_start_line": best["start_idx"] + 1,
        "matched_insertion_idx": best["insertion_idx"],
        "matched_insertion_line": best["insertion_idx"] + 1,
        "matched_old_count": best["matched_old_count"],
        "header_old_start": int(hunk["header_old_start"]),
        "header_line_delta": best["header_delta"],
        "used_header_proximity_tiebreak": len(candidates) > 1,
        "deletions_match": best["deletions_match"],
        "context_lines_used": best["context_lines"],
        "context_chars_used": best["context_chars"],
    }


def _materialize_hunk_blocks(hunk: dict[str, Any]) -> tuple[list[str], list[str]]:
    old_block: list[str] = []
    new_block: list[str] = []
    for line in hunk["lines"]:
        if line == r"\ No newline at end of file":
            continue
        marker = line[0]
        value = line[1:]
        if marker == " ":
            old_block.append(value)
            new_block.append(value)
        elif marker == "-":
            old_block.append(value)
        elif marker == "+":
            new_block.append(value)
    return old_block, new_block


def _apply_hunk_at_position(original_lines: list[str], start_idx: int, hunk: dict[str, Any]) -> tuple[list[str], dict[str, Any]] | None:
    if start_idx < 0:
        return None
    old_block, new_block = _materialize_hunk_blocks(hunk)
    end_idx = start_idx + len(old_block)
    if end_idx > len(original_lines):
        return None
    if original_lines[start_idx:end_idx] != old_block:
        return None
    updated_lines = list(original_lines[:start_idx]) + new_block + list(original_lines[end_idx:])
    diag = {
        "matched_start_idx": start_idx,
        "matched_start_line": start_idx + 1,
        "matched_old_count": len(old_block),
        "header_line_delta": start_idx - (0 if int(hunk["header_old_start"]) == 0 else int(hunk["header_old_start"]) - 1),
    }
    return updated_lines, diag


def _render_lines_after_apply(
    original_text: str, updated_lines: list[str], force_no_trailing_newline: bool | None = None
) -> str:
    with_newline = "\n".join(updated_lines) + ("\n" if original_text.endswith("\n") else "")
    if force_no_trailing_newline:
        return with_newline[:-1] if with_newline.endswith("\n") else with_newline
    return with_newline


def _apply_parsed_hunks_tolerant(
    original_text: str, hunks: list[dict[str, Any]], force_no_trailing_newline: bool | None = None
) -> tuple[str, list[dict[str, Any]], bool]:
    current_lines = original_text.splitlines()
    diagnostics: list[dict[str, Any]] = []
    cursor = 0
    used_locator = False

    for hunk in hunks:
        hunk_index = int(hunk["hunk_index"])
        declared_start = 0 if int(hunk["header_old_start"]) == 0 else int(hunk["header_old_start"]) - 1
        strict_result = None
        if declared_start >= cursor:
            strict_result = _apply_hunk_at_position(current_lines, declared_start, hunk)
        if strict_result is not None:
            current_lines, strict_diag = strict_result
            cursor = int(strict_diag["matched_start_idx"]) + int(strict_diag["matched_old_count"])
            diagnostics.append(
                {
                    "hunk_index": hunk_index,
                    "strategy": "strict_position",
                    "candidate_count": 1,
                    "matched_line": int(strict_diag["matched_start_line"]),
                    "header_delta": int(strict_diag["header_line_delta"]),
                    "count_mismatch": bool(hunk["has_count_mismatch"]),
                }
            )
            continue

        choice = _choose_hunk_candidate(current_lines, hunk, min_start_idx=cursor)
        if not choice["matched"]:
            reason = str(choice["reason"])
            if reason == "ambiguous_context_match":
                raise ValueError(
                    f"autofix could not locate hunk {hunk_index}: ambiguous context match ({choice['top_candidate_count']} top candidates)"
                )
            if reason == "insufficient_context":
                raise ValueError(f"autofix could not locate hunk {hunk_index}: insufficient context")
            raise ValueError(f"autofix could not locate hunk {hunk_index}: no context match")

        located_result = _apply_hunk_at_position(current_lines, int(choice["matched_start_idx"]), hunk)
        if located_result is None:
            raise ValueError(f"autofix located hunk {hunk_index} but failed to apply it")
        current_lines, strict_diag = located_result
        cursor = int(strict_diag["matched_start_idx"]) + int(strict_diag["matched_old_count"])
        diagnostics.append(
            {
                "hunk_index": hunk_index,
                "strategy": "locator_exact_context",
                "candidate_count": int(choice["candidate_count"]),
                "matched_line": int(choice["matched_start_line"]),
                "header_delta": int(choice["header_line_delta"]),
                "count_mismatch": bool(hunk["has_count_mismatch"]),
                "header_tiebreak": bool(choice["used_header_proximity_tiebreak"]),
            }
        )
        used_locator = True

    return _render_lines_after_apply(original_text, current_lines, force_no_trailing_newline), diagnostics, used_locator


def _apply_parsed_hunks(
    original_text: str, hunks: list[dict[str, Any]], force_no_trailing_newline: bool | None = None
) -> str:
    original_lines = original_text.splitlines()
    out_lines: list[str] = []
    cursor = 0

    for hunk in hunks:
        old_start = int(hunk["old_start"])
        old_count = int(hunk["old_count"])
        new_count = int(hunk["new_count"])
        hunk_lines = list(hunk["lines"])

        start_idx = 0 if old_start == 0 else old_start - 1
        if start_idx < cursor:
            raise ValueError("overlapping hunks are not supported")
        if start_idx > len(original_lines):
            raise ValueError("hunk start is out of file bounds")

        out_lines.extend(original_lines[cursor:start_idx])

        local_old = 0
        local_new = 0
        file_idx = start_idx
        for line in hunk_lines:
            if line == r"\ No newline at end of file":
                continue
            marker = line[0]
            value = line[1:]
            if marker == " ":
                if file_idx >= len(original_lines) or original_lines[file_idx] != value:
                    raise ValueError("hunk context mismatch")
                out_lines.append(value)
                file_idx += 1
                local_old += 1
                local_new += 1
            elif marker == "-":
                if file_idx >= len(original_lines) or original_lines[file_idx] != value:
                    raise ValueError("hunk delete line mismatch")
                file_idx += 1
                local_old += 1
            elif marker == "+":
                out_lines.append(value)
                local_new += 1
            else:
                raise ValueError("invalid hunk line prefix")

        if local_old != old_count or local_new != new_count:
            raise ValueError("hunk line counts do not match content")
        cursor = file_idx

    out_lines.extend(original_lines[cursor:])
    return _render_lines_after_apply(original_text, out_lines, force_no_trailing_newline)


def _atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".crud_skill_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


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


class CrudPrePostProcessing:
    def describe(self) -> PrePostProcessingSpec:
        return PrePostProcessingSpec(
            prepost_processing_id="crud-processing",
            name="CRUD Pre/Post Processing",
            version="0.1.0",
            description="Performs file CRUD only inside configured root_dir.",
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
        max_content_bytes = merged.get("max_content_bytes", 4096)
        max_list_entries = merged.get("max_list_entries", 100)
        max_diff_bytes = merged.get("max_diff_bytes", 20_000)
        max_diff_lines = merged.get("max_diff_lines", 1000)
        allowed_diff_modes = merged.get("allowed_diff_modes", list(ALLOWED_DIFF_MODES))
        try:
            _ensure_int(max_content_bytes, "max_content_bytes", 1, 100_000)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _ensure_int(max_list_entries, "max_list_entries", 1, 1000)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _ensure_int(max_diff_bytes, "max_diff_bytes", 64, 200_000)
        except ValueError as exc:
            errors.append(str(exc))
        try:
            _ensure_int(max_diff_lines, "max_diff_lines", 1, 20_000)
        except ValueError as exc:
            errors.append(str(exc))
        if not isinstance(allowed_diff_modes, list) or not allowed_diff_modes:
            errors.append("allowed_diff_modes must be a non-empty list")
        elif any(item not in ALLOWED_DIFF_MODES for item in allowed_diff_modes):
            errors.append("allowed_diff_modes contains unsupported mode")
        return errors

    def run(self, ctx: PrePostProcessingContext, payload: dict) -> PrePostProcessingResult:
        _ = ctx
        try:
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            config = _merge_config(payload.get("config", {}))
            root = _resolve_root(config.get("root_dir"))
            max_content_bytes = _ensure_int(config.get("max_content_bytes", 4096), "max_content_bytes", 1, 100_000)
            max_list_entries = _ensure_int(config.get("max_list_entries", 100), "max_list_entries", 1, 1000)
            max_diff_bytes = _ensure_int(config.get("max_diff_bytes", 20_000), "max_diff_bytes", 64, 200_000)
            max_diff_lines = _ensure_int(config.get("max_diff_lines", 1000), "max_diff_lines", 1, 20_000)
            allowed_diff_modes = config.get("allowed_diff_modes", list(ALLOWED_DIFF_MODES))
            if not isinstance(allowed_diff_modes, list) or not allowed_diff_modes:
                raise ValueError("allowed_diff_modes must be a non-empty list")
            if any(item not in ALLOWED_DIFF_MODES for item in allowed_diff_modes):
                raise ValueError("allowed_diff_modes contains unsupported mode")
            data = _load_data(payload)

            operation = data.get("operation")
            if not isinstance(operation, str) or not operation:
                raise ValueError("operation is required and must be a string")

            if operation == "create":
                return self._op_create(root, data, max_content_bytes)
            if operation == "update":
                return self._op_update(root, data, max_content_bytes)
            if operation == "delete":
                return self._op_delete(root, data)
            if operation == "read":
                return self._op_read(root, data, max_content_bytes)
            if operation == "list":
                return self._op_list(root, data, max_list_entries)
            if operation == "diff_apply":
                return self._op_diff_apply(root, data, max_diff_bytes, max_diff_lines, tuple(allowed_diff_modes))
            raise ValueError("unsupported operation")
        except Exception as exc:
            return PrePostProcessingResult(status="error", error=str(exc), output={}, metadata={})

    def _op_diff_apply(
        self,
        root: Path,
        data: dict[str, Any],
        max_diff_bytes: int,
        max_diff_lines: int,
        allowed_diff_modes: tuple[str, ...],
    ) -> PrePostProcessingResult:
        target, normalized = _resolve_inside_root(root, data.get("path"), strict=False)
        mode = data.get("mode", "strict")
        if not isinstance(mode, str) or mode not in allowed_diff_modes:
            raise ValueError("mode is invalid for diff_apply")
        raw_diff_text = _ensure_string(data.get("diff_text"), "diff_text")
        autofix_applied = False
        if mode == "autofix":
            diff_text, autofix_applied = _autofix_diff_text(raw_diff_text)
        else:
            if "\r" in raw_diff_text:
                raise ValueError("diff_text contains CR characters; use mode=autofix")
            diff_text = raw_diff_text
        diff_bytes = len(diff_text.encode("utf-8"))
        if diff_bytes > max_diff_bytes:
            raise ValueError("diff_text exceeds max_diff_bytes")
        parsed = _parse_unified_diff(diff_text, normalized, max_diff_lines, tolerant=mode == "autofix")

        dry_run = data.get("dry_run", True)
        dry_run_bool = _ensure_bool(dry_run, "dry_run")
        expected_sha256 = data.get("expected_sha256")
        if expected_sha256 is not None:
            _ensure_string(expected_sha256, "expected_sha256")
            if not SHA256_RE.fullmatch(expected_sha256):
                raise ValueError("expected_sha256 must be lowercase hex sha256")

        before_bytes = _read_file_bytes(target)
        before_sha256 = _hash_bytes(before_bytes)
        if expected_sha256 is not None and before_sha256 != expected_sha256:
            raise ValueError("expected_sha256 mismatch")
        before_text = before_bytes.decode("utf-8", errors="strict")
        hunk_diagnostics: list[dict[str, Any]] = []
        if mode == "autofix":
            after_text, hunk_diagnostics, tolerant_used = _apply_parsed_hunks_tolerant(
                before_text, parsed["hunks"], force_no_trailing_newline=parsed["force_no_trailing_newline"]
            )
            autofix_applied = autofix_applied or tolerant_used or any(
                bool(hunk["has_count_mismatch"]) for hunk in parsed["hunks"]
            )
        else:
            after_text = _apply_parsed_hunks(
                before_text, parsed["hunks"], force_no_trailing_newline=parsed["force_no_trailing_newline"]
            )
        after_bytes = after_text.encode("utf-8")
        after_sha256 = _hash_bytes(after_bytes)

        applied = False
        if not dry_run_bool and after_bytes != before_bytes:
            _atomic_write_text(target, after_text)
            applied = True

        return PrePostProcessingResult(
            status="ok",
            output={
                "operation": "diff_apply",
                "path": normalized,
                "mode": mode,
                "dry_run": dry_run_bool,
                "diff_bytes": diff_bytes,
                "diff_lines": parsed["line_count"],
                "hunk_count": parsed["hunk_count"],
                "target_exists": target.exists(),
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "autofix_applied": autofix_applied,
                "hunk_diagnostics": hunk_diagnostics,
                "applied": applied,
            },
        )

    def _op_create(self, root: Path, data: dict[str, Any], max_content_bytes: int) -> PrePostProcessingResult:
        target, normalized = _resolve_inside_root(root, data.get("path"), strict=False)
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > max_content_bytes:
            raise ValueError("content exceeds max_content_bytes")
        create_parents = bool(data.get("create_parents", False))
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        parent = target.parent.resolve(strict=True)
        if os.path.commonpath([str(root), str(parent)]) != str(root):
            raise ValueError("path escapes root_dir")
        if target.exists():
            raise ValueError("target already exists")
        target.write_text(content, encoding="utf-8")
        return PrePostProcessingResult(status="ok", output={"operation": "create", "path": normalized, "bytes": len(encoded)})

    def _op_update(self, root: Path, data: dict[str, Any], max_content_bytes: int) -> PrePostProcessingResult:
        target, normalized = _resolve_inside_root(root, data.get("path"), strict=False)
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError("content is required and must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > max_content_bytes:
            raise ValueError("content exceeds max_content_bytes")
        create_if_missing = bool(data.get("create_if_missing", False))
        create_parents = bool(data.get("create_parents", False))
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        created = not target.exists()
        if not target.exists() and not create_if_missing:
            raise ValueError("target does not exist")
        if target.exists() and target.is_dir():
            raise ValueError("target is a directory")
        target.write_text(content, encoding="utf-8")
        return PrePostProcessingResult(
            status="ok",
            output={
                "operation": "update",
                "path": normalized,
                "bytes": len(encoded),
                "created": bool(created and create_if_missing),
            },
        )

    def _op_delete(self, root: Path, data: dict[str, Any]) -> PrePostProcessingResult:
        target, normalized = _resolve_inside_root(root, data.get("path"), strict=True)
        recursive = bool(data.get("recursive", False))
        if target == root:
            raise ValueError("refusing to delete root_dir")
        if target.is_file() or target.is_symlink():
            target.unlink()
            deleted_type = "file"
        elif target.is_dir():
            if recursive:
                shutil.rmtree(target)
            else:
                target.rmdir()
            deleted_type = "dir"
        else:
            raise ValueError("target is neither file nor directory")
        return PrePostProcessingResult(status="ok", output={"operation": "delete", "path": normalized, "deleted_type": deleted_type})

    def _op_read(self, root: Path, data: dict[str, Any], max_content_bytes: int) -> PrePostProcessingResult:
        target, normalized = _resolve_inside_root(root, data.get("path"), strict=True)
        if not target.is_file():
            raise ValueError("target must be a file")
        read_limit = _ensure_int(data.get("max_bytes", max_content_bytes), "max_bytes", 1, max_content_bytes)
        raw = target.read_bytes()
        truncated = len(raw) > read_limit
        raw = raw[:read_limit]
        text = raw.decode("utf-8", errors="replace")
        return PrePostProcessingResult(
            status="ok",
            output={"operation": "read", "path": normalized, "content": text, "truncated": truncated, "bytes": len(raw)},
        )

    def _op_list(self, root: Path, data: dict[str, Any], max_list_entries: int) -> PrePostProcessingResult:
        rel_path = data.get("path", ".")
        target, normalized = _resolve_inside_root(root, rel_path, allow_dot=True, strict=True)
        if not target.is_dir():
            raise ValueError("target must be a directory")
        limit = _ensure_int(data.get("limit", max_list_entries), "limit", 1, max_list_entries)
        entries = []
        for item in sorted(target.iterdir(), key=lambda p: p.name)[:limit]:
            if item.is_dir():
                kind = "dir"
            elif item.is_file():
                kind = "file"
            else:
                kind = "other"
            entries.append({"name": item.name, "type": kind})
        return PrePostProcessingResult(
            status="ok",
            output={"operation": "list", "path": normalized, "entries": entries, "count": len(entries)},
        )


def create_processor() -> CrudPrePostProcessing:
    return CrudPrePostProcessing()
