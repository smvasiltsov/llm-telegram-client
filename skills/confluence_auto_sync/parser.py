from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConfluenceMeta:
    data: dict[str, Any]


@dataclass(frozen=True)
class ParsedDoc:
    doc_path: str
    abs_path: str
    folder_path: str
    is_index: bool
    title: str
    body_markdown: str
    content_hash: str
    confluence: dict[str, Any]
    sync: dict[str, Any]
    effective_space_id: str


@dataclass
class ParseResult:
    docs_root: str
    docs_root_abs: str
    meta: ConfluenceMeta | None = None
    docs: list[ParsedDoc] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_confluence_docs(repo_path: str | Path, docs_root: str = "confluence_docs") -> ParseResult:
    repo = Path(repo_path).expanduser().resolve()
    root = (repo / docs_root).resolve()
    result = ParseResult(docs_root=docs_root, docs_root_abs=str(root))

    if not root.exists() or not root.is_dir():
        result.errors.append(f"docs_root directory does not exist: {root}")
        return result

    meta_path = root / "_meta.yaml"
    result.meta = _read_meta(meta_path=meta_path, errors=result.errors)

    markdown_files = sorted(path for path in root.rglob("*.md") if path.is_file())
    for path in markdown_files:
        parsed = _parse_markdown_doc(path=path, docs_root=root, errors=result.errors)
        if parsed is not None:
            result.docs.append(parsed)

    return result


def _read_meta(meta_path: Path, errors: list[str]) -> ConfluenceMeta | None:
    if not meta_path.exists() or not meta_path.is_file():
        errors.append(f"missing _meta.yaml: {meta_path}")
        return None

    try:
        raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(f"invalid YAML in {meta_path}: {exc}")
        return None

    if not isinstance(raw, dict):
        errors.append(f"_meta.yaml must be an object: {meta_path}")
        return None

    return ConfluenceMeta(data=raw)


def _parse_markdown_doc(path: Path, docs_root: Path, errors: list[str]) -> ParsedDoc | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"failed to read {path}: {exc}")
        return None

    front_matter, body = _extract_front_matter(text=text, path=path, errors=errors)
    if front_matter is None:
        return None

    if not isinstance(front_matter, dict):
        errors.append(f"front matter must be an object: {path}")
        return None

    title = front_matter.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"title is required in front matter: {path}")
        return None

    confluence_raw = front_matter.get("confluence")
    if not isinstance(confluence_raw, dict):
        errors.append(f"confluence section is required in front matter: {path}")
        return None
    space_id = _normalize_id(confluence_raw.get("space_id")) or ""

    sync_raw = front_matter.get("sync")
    if not isinstance(sync_raw, dict):
        errors.append(f"sync section is required in front matter: {path}")
        return None

    mode = sync_raw.get("mode")
    if mode != "publish":
        errors.append(f"sync.mode must be 'publish': {path}")
        return None

    rel_path = path.relative_to(docs_root).as_posix()
    folder_path = path.parent.relative_to(docs_root).as_posix()
    if folder_path == ".":
        folder_path = ""

    confluence = {
        "space_id": space_id,
        "page_id": _normalize_id(confluence_raw.get("page_id")),
        "parent_page_id": _normalize_id(confluence_raw.get("parent_page_id")),
        "local_id": _normalize_str(confluence_raw.get("local_id")),
        "parent_local_id": _normalize_str(confluence_raw.get("parent_local_id")),
        "parent_doc_path": _normalize_path(confluence_raw.get("parent_doc_path")),
        "status": _normalize_str(confluence_raw.get("status")),
        "labels": _normalize_labels(confluence_raw.get("labels")),
    }
    sync = {
        "mode": "publish",
        "delete_policy": _normalize_str(sync_raw.get("delete_policy")),
        "owner": _normalize_str(sync_raw.get("owner")),
        "last_reviewed": _normalize_str(sync_raw.get("last_reviewed")),
    }

    return ParsedDoc(
        doc_path=rel_path,
        abs_path=str(path.resolve()),
        folder_path=folder_path,
        is_index=path.name == "_index.md",
        title=title.strip(),
        body_markdown=body,
        content_hash=_hash_content(body),
        confluence=confluence,
        sync=sync,
        effective_space_id=space_id,
    )


def _extract_front_matter(text: str, path: Path, errors: list[str]) -> tuple[dict[str, Any] | None, str]:
    if not text.startswith("---\n") and text != "---":
        errors.append(f"front matter is required and must start with '---': {path}")
        return None, ""

    end_marker = "\n---\n"
    end_index = text.find(end_marker, 4)
    if end_index == -1:
        if text.endswith("\n---"):
            fm_text = text[4:-4]
            body = ""
        else:
            errors.append(f"front matter closing '---' not found: {path}")
            return None, ""
    else:
        fm_text = text[4:end_index]
        body = text[end_index + len(end_marker) :]

    try:
        parsed = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        errors.append(f"invalid front matter YAML in {path}: {exc}")
        return None, ""

    return parsed, body


def _normalize_id(value: Any) -> str | None:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
    return labels


def _normalize_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        return None
    return normalized.lstrip("./")


def _hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
