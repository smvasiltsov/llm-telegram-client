from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from skills.confluence_auto_sync.parser import ParsedDoc


@dataclass(frozen=True)
class ResolvedDoc:
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
    resolved_parent_page_id: str | None
    resolved_parent_doc_path: str | None
    parent_source: str  # explicit|folder_index|root


@dataclass
class TreeBuildResult:
    ordered_docs: list[ResolvedDoc] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_publish_tree(
    docs: list[ParsedDoc],
    meta_data: dict[str, Any] | None,
    *,
    prefer_root_for_top_level: bool = False,
) -> TreeBuildResult:
    result = TreeBuildResult()
    meta_data = meta_data or {}

    root_page_id = _normalize_id(_nested_get(meta_data, ["confluence", "root_page_id"]))
    if not root_page_id:
        result.errors.append("_meta.yaml confluence.root_page_id is required for tree resolution")
        return result

    sorted_docs = sorted(docs, key=_sort_key)
    index_by_folder: dict[str, ParsedDoc] = {
        doc.folder_path: doc for doc in sorted_docs if doc.is_index
    }
    docs_by_path: dict[str, ParsedDoc] = {doc.doc_path: doc for doc in sorted_docs}
    index_by_local_id: dict[str, ParsedDoc] = {}
    for doc in sorted_docs:
        local_id = _normalize_str(doc.confluence.get("local_id"))
        if local_id:
            index_by_local_id[local_id] = doc

    for doc in sorted_docs:
        resolved_parent, resolved_parent_doc_path, source, err = _resolve_parent_page_id(
            doc=doc,
            index_by_folder=index_by_folder,
            docs_by_path=docs_by_path,
            index_by_local_id=index_by_local_id,
            root_page_id=root_page_id,
            prefer_root_for_top_level=prefer_root_for_top_level,
        )
        if err:
            result.errors.append(err)
            continue
        result.ordered_docs.append(
            ResolvedDoc(
                doc_path=doc.doc_path,
                abs_path=doc.abs_path,
                folder_path=doc.folder_path,
                is_index=doc.is_index,
                title=doc.title,
                body_markdown=doc.body_markdown,
                content_hash=doc.content_hash,
                confluence=dict(doc.confluence),
                sync=dict(doc.sync),
                effective_space_id=doc.effective_space_id,
                resolved_parent_page_id=resolved_parent,
                resolved_parent_doc_path=resolved_parent_doc_path,
                parent_source=source,
            )
        )
    return result


def _resolve_parent_page_id(
    *,
    doc: ParsedDoc,
    index_by_folder: dict[str, ParsedDoc],
    docs_by_path: dict[str, ParsedDoc],
    index_by_local_id: dict[str, ParsedDoc],
    root_page_id: str,
    prefer_root_for_top_level: bool,
) -> tuple[str | None, str | None, str, str | None]:
    folder = doc.folder_path
    if folder:
        parent_folder = PurePosixPath(folder).parent.as_posix()
        if parent_folder == ".":
            parent_folder = ""
    else:
        parent_folder = ""

    # With root override, only the real docs root anchor (`/_index.md`)
    # is forcibly re-parented to root.
    if prefer_root_for_top_level and doc.is_index and doc.folder_path == "":
        return root_page_id, None, "root", None

    parent_doc_path = _normalize_path(doc.confluence.get("parent_doc_path"))
    if parent_doc_path:
        parent_doc = docs_by_path.get(parent_doc_path)
        if parent_doc is None:
            return None, None, "doc_ref", f"parent_doc_path target not found for {doc.doc_path}: {parent_doc_path}"
        ref_page_id = _normalize_id(parent_doc.confluence.get("page_id"))
        return ref_page_id, parent_doc.doc_path, "doc_ref", None

    parent_local_id = _normalize_str(doc.confluence.get("parent_local_id"))
    if parent_local_id:
        parent_doc = index_by_local_id.get(parent_local_id)
        if parent_doc is None:
            return None, None, "local_ref", f"parent_local_id target not found for {doc.doc_path}: {parent_local_id}"
        ref_page_id = _normalize_id(parent_doc.confluence.get("page_id"))
        return ref_page_id, parent_doc.doc_path, "local_ref", None

    explicit_parent = _normalize_id(doc.confluence.get("parent_page_id"))
    if explicit_parent:
        return explicit_parent, None, "explicit", None

    # For non-_index documents inside a folder:
    # parent is this folder's _index page id when present.
    # If folder _index is absent, fall back to root page id.
    if doc.folder_path and not doc.is_index:
        folder_index = index_by_folder.get(doc.folder_path)
        if folder_index is not None:
            index_page_id = _normalize_id(folder_index.confluence.get("page_id"))
            if index_page_id:
                return index_page_id, None, "folder_index", None
            return None, folder_index.doc_path, "folder_index", None
        return root_page_id, None, "root", None

    # For folder _index (or root docs), inherit from parent folder _index.
    parent_index = index_by_folder.get(parent_folder)
    if parent_index is not None:
        if parent_index.doc_path == doc.doc_path:
            # Prevent self-parent for root _index.md.
            return root_page_id, None, "root", None
        index_page_id = _normalize_id(parent_index.confluence.get("page_id"))
        if index_page_id:
            return index_page_id, None, "folder_index", None
        return None, parent_index.doc_path, "folder_index", None

    return root_page_id, None, "root", None


def _sort_key(doc: ParsedDoc) -> tuple[str, int, str]:
    # Folder-first lexical order and _index.md before other files in each folder.
    return (doc.folder_path, 0 if doc.is_index else 1, doc.doc_path)


def _nested_get(payload: dict[str, Any], path: list[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_id(value: Any) -> str | None:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        return None
    return normalized.lstrip("./")


def _normalize_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
