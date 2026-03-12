from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class FrontmatterUpdate:
    file_path: str
    page_id: str
    space_id: str | None = None
    parent_page_id: str | None = None
    doc_path: str | None = None


@dataclass(frozen=True)
class FrontmatterRewriteItem:
    path: str
    page_id: str | None = None
    reason: str | None = None
    error: str | None = None


@dataclass
class FrontmatterRewriteResult:
    rewritten: list[FrontmatterRewriteItem] = field(default_factory=list)
    skipped: list[FrontmatterRewriteItem] = field(default_factory=list)
    errors: list[FrontmatterRewriteItem] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "rewritten": len(self.rewritten),
            "skipped": len(self.skipped),
            "errors": len(self.errors),
        }

    def to_output(self) -> dict[str, object]:
        return {
            "rewritten": [item.__dict__ for item in self.rewritten],
            "skipped": [item.__dict__ for item in self.skipped],
            "errors": [item.__dict__ for item in self.errors],
            "summary": self.summary(),
        }


def rewrite_frontmatter_ids(updates: Iterable[FrontmatterUpdate]) -> FrontmatterRewriteResult:
    result = FrontmatterRewriteResult()
    for update in updates:
        path = Path(update.file_path).expanduser().resolve()
        item_path = update.doc_path or str(path)
        page_id = str(update.page_id).strip()
        if not page_id:
            result.errors.append(
                FrontmatterRewriteItem(path=item_path, page_id=None, error="empty page_id")
            )
            continue
        if not path.exists() or not path.is_file():
            result.errors.append(
                FrontmatterRewriteItem(path=item_path, page_id=page_id, error=f"file not found: {path}")
            )
            continue

        try:
            source_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            result.errors.append(
                FrontmatterRewriteItem(path=item_path, page_id=page_id, error=f"read failed: {exc}")
            )
            continue

        parsed = _split_frontmatter(source_text)
        if parsed is None:
            result.skipped.append(
                FrontmatterRewriteItem(path=item_path, page_id=page_id, reason="front matter not found")
            )
            continue

        start_delim, front_matter_text, end_delim, body_text = parsed
        rewritten_front_matter_text, changed = _rewrite_front_matter_text(
            front_matter_text=front_matter_text,
            page_id=page_id,
            space_id=update.space_id,
            parent_page_id=update.parent_page_id,
        )
        if not changed:
            result.skipped.append(
                FrontmatterRewriteItem(path=item_path, page_id=page_id, reason="page_id already up to date")
            )
            continue

        rewritten_text = f"{start_delim}{rewritten_front_matter_text}{end_delim}{body_text}"
        try:
            _atomic_write(path, rewritten_text)
        except OSError as exc:
            result.errors.append(
                FrontmatterRewriteItem(path=item_path, page_id=page_id, error=f"write failed: {exc}")
            )
            continue

        result.rewritten.append(FrontmatterRewriteItem(path=item_path, page_id=page_id))

    return result


def _rewrite_front_matter_text(
    *,
    front_matter_text: str,
    page_id: str,
    space_id: str | None,
    parent_page_id: str | None,
) -> tuple[str, bool]:
    line_break = "\r\n" if "\r\n" in front_matter_text else "\n"
    lines = front_matter_text.splitlines(keepends=True)
    if not lines:
        lines = []

    # Validate YAML before rewrite to avoid corrupting malformed metadata.
    before = yaml.safe_load(front_matter_text or "{}")
    if before is not None and not isinstance(before, dict):
        raise ValueError("front matter must be a YAML object")

    changed = False
    confluence_index = _find_top_level_key_line(lines, key="confluence")
    if confluence_index is None:
        changed = True
        if lines and not lines[-1].endswith(("\n", "\r\n")):
            lines[-1] = f"{lines[-1]}{line_break}"
        lines.append(f"confluence:{line_break}")
        lines.append(f"  page_id: {_yaml_scalar(page_id)}{line_break}")
        if space_id:
            lines.append(f"  space_id: {_yaml_scalar(space_id)}{line_break}")
        if parent_page_id:
            lines.append(f"  parent_page_id: {_yaml_scalar(parent_page_id)}{line_break}")
    else:
        changed = _upsert_page_id_in_confluence_block(
            lines=lines,
            confluence_index=confluence_index,
            page_id=page_id,
            space_id=space_id,
            parent_page_id=parent_page_id,
            line_break=line_break,
        )

    rewritten = "".join(lines)
    after = yaml.safe_load(rewritten or "{}")
    if after is not None and not isinstance(after, dict):
        raise ValueError("rewritten front matter must be a YAML object")
    return rewritten, changed


def _upsert_page_id_in_confluence_block(
    *,
    lines: list[str],
    confluence_index: int,
    page_id: str,
    space_id: str | None,
    parent_page_id: str | None,
    line_break: str,
) -> bool:
    confluence_line = lines[confluence_index]
    base_indent = _leading_spaces(confluence_line)
    content = confluence_line.strip()
    # If `confluence` is inline map (`confluence: {page_id: 1}`), replace with block style.
    if not re.match(r"^confluence:\s*(#.*)?$", content):
        lines[confluence_index] = f"{' ' * base_indent}confluence:{line_break}"
        insert_at = confluence_index + 1
        lines.insert(insert_at, f"{' ' * (base_indent + 2)}page_id: {_yaml_scalar(page_id)}{line_break}")
        if space_id:
            lines.insert(insert_at + 1, f"{' ' * (base_indent + 2)}space_id: {_yaml_scalar(space_id)}{line_break}")
        if parent_page_id:
            lines.insert(insert_at + 2, f"{' ' * (base_indent + 2)}parent_page_id: {_yaml_scalar(parent_page_id)}{line_break}")
        return True

    block_end = _find_top_level_block_end(lines=lines, start_index=confluence_index + 1)
    child_indent = _detect_child_indent(
        lines=lines,
        block_start=confluence_index + 1,
        block_end=block_end,
        default_indent=base_indent + 2,
    )

    changed = False
    changed = _upsert_field(
        lines=lines,
        block_start=confluence_index + 1,
        block_end=block_end,
        min_indent=child_indent,
        key="page_id",
        value=_yaml_scalar(page_id),
        line_break=line_break,
    ) or changed
    if space_id:
        changed = _upsert_field(
            lines=lines,
            block_start=confluence_index + 1,
            block_end=block_end,
            min_indent=child_indent,
            key="space_id",
            value=_yaml_scalar(space_id),
            line_break=line_break,
        ) or changed
    if parent_page_id:
        changed = _upsert_field(
            lines=lines,
            block_start=confluence_index + 1,
            block_end=block_end,
            min_indent=child_indent,
            key="parent_page_id",
            value=_yaml_scalar(parent_page_id),
            line_break=line_break,
        ) or changed
    return changed


def _split_frontmatter(text: str) -> tuple[str, str, str, str] | None:
    if not text:
        return None
    lines = text.splitlines(keepends=True)
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            start_delim = lines[0]
            front_matter_text = "".join(lines[1:idx])
            end_delim = lines[idx]
            body = "".join(lines[idx + 1 :])
            return start_delim, front_matter_text, end_delim, body
    return None


def _find_top_level_key_line(lines: list[str], *, key: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    for index, line in enumerate(lines):
        if _leading_spaces(line) != 0:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if pattern.match(stripped):
            return index
    return None


def _find_top_level_block_end(*, lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _leading_spaces(line) == 0:
            return index
    return len(lines)


def _detect_child_indent(
    *,
    lines: list[str],
    block_start: int,
    block_end: int,
    default_indent: int,
) -> int:
    for idx in range(block_start, block_end):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _leading_spaces(line)
        if indent > default_indent - 1:
            return indent
    return default_indent


def _find_field_line(
    *,
    lines: list[str],
    block_start: int,
    block_end: int,
    min_indent: int,
    key: str,
) -> int | None:
    for idx in range(block_start, block_end):
        line = lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _leading_spaces(line)
        if indent < min_indent:
            continue
        if re.match(rf"^{re.escape(key)}\s*:", stripped):
            return idx
    return None


def _upsert_field(
    *,
    lines: list[str],
    block_start: int,
    block_end: int,
    min_indent: int,
    key: str,
    value: str,
    line_break: str,
) -> bool:
    field_index = _find_field_line(
        lines=lines,
        block_start=block_start,
        block_end=block_end,
        min_indent=min_indent,
        key=key,
    )
    if field_index is not None:
        original = lines[field_index]
        pattern = re.compile(
            rf"^(\s*{re.escape(key)}:\s*)([^#\r\n]*)(\s*(?:#.*)?)(\r?\n)?$"
        )
        replacement = pattern.sub(
            lambda match: f"{match.group(1)}{value}{match.group(3)}{match.group(4) or ''}",
            original,
        )
        if replacement == original:
            return False
        lines[field_index] = replacement
        return True
    lines.insert(block_start, f"{' ' * min_indent}{key}: {value}{line_break}")
    return True


def _yaml_scalar(value: str) -> str:
    if re.match(r"^[A-Za-z0-9_.-]+$", value):
        return value
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
    if dumped.startswith("---"):
        dumped = dumped.replace("---", "", 1).strip()
    return dumped


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        newline="",
    ) as temp_file:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, path)
