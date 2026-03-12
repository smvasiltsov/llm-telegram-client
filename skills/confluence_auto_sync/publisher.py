from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from skills.confluence.client import ConfluenceClient, ConfluenceClientConfig, ConfluenceHTTPError
from skills.confluence_auto_sync.state import PublishState, StateRecord
from skills.confluence_auto_sync.tree import ResolvedDoc


@dataclass(frozen=True)
class PublishOptions:
    mode: str  # dry-run|apply
    changed_only: bool
    update_if_changed_only: bool
    safe_mode: bool
    fail_on_drift: bool
    rewrite_frontmatter_ids: bool
    strict_parent_update: bool = False
    target_space_id: str | None = None


@dataclass(frozen=True)
class PublishItem:
    path: str
    page_id: str | None = None
    space_id: str | None = None
    parent_page_id: str | None = None
    reason: str | None = None
    error: str | None = None
    warning: str | None = None


@dataclass
class PublishResult:
    created: list[PublishItem] = field(default_factory=list)
    updated: list[PublishItem] = field(default_factory=list)
    skipped: list[PublishItem] = field(default_factory=list)
    errors: list[PublishItem] = field(default_factory=list)
    warnings: list[PublishItem] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "created": len(self.created),
            "updated": len(self.updated),
            "skipped": len(self.skipped),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
        }

    def to_output(self) -> dict[str, Any]:
        return {
            "created": [item.__dict__ for item in self.created],
            "updated": [item.__dict__ for item in self.updated],
            "skipped": [item.__dict__ for item in self.skipped],
            "errors": [item.__dict__ for item in self.errors],
            "warnings": [item.__dict__ for item in self.warnings],
            "summary": self.summary(),
        }


class ConfluencePublisher:
    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile
        conf = profile.get("confluence", {}) if isinstance(profile, dict) else {}
        client_config = ConfluenceClientConfig(
            url=str(conf.get("url", "")).strip(),
            timeout_sec=_int(conf.get("timeout_sec"), default=30),
            retry_attempts=_int(conf.get("retry_attempts"), default=3),
            retry_sleep_sec=float(conf.get("retry_sleep_sec", 3)),
        )
        self._client = ConfluenceClient(
            config=client_config,
            username=str(conf.get("username", "")).strip(),
            token=str(conf.get("token", "")).strip(),
        )
        self._page_id_remap: dict[str, str] = {}
        self._doc_path_page_id: dict[str, str] = {}

    def publish(
        self,
        *,
        docs: list[ResolvedDoc],
        state: PublishState,
        options: PublishOptions,
        process_orphans: bool = True,
        all_active_doc_paths: set[str] | None = None,
    ) -> PublishResult:
        result = PublishResult()

        active_paths: set[str] = set(all_active_doc_paths or set())
        for doc in docs:
            active_paths.add(doc.doc_path)
            self._publish_doc(doc=doc, state=state, options=options, result=result)

        if process_orphans:
            self._delete_orphans(active_doc_paths=active_paths, state=state, options=options, result=result)
        return result

    def _publish_doc(self, *, doc: ResolvedDoc, state: PublishState, options: PublishOptions, result: PublishResult) -> None:
        parent_id = self._resolve_parent_id(doc=doc, state=state)

        should_publish = state.changed(
            doc_path=doc.doc_path,
            content_hash=doc.content_hash,
            changed_only=options.changed_only,
            update_if_changed_only=options.update_if_changed_only,
        )
        if not should_publish:
            result.skipped.append(
                PublishItem(
                    path=doc.doc_path,
                    page_id=doc.confluence.get("page_id"),
                    space_id=doc.effective_space_id,
                    parent_page_id=parent_id,
                    reason="unchanged",
                )
            )
            return

        page_id = _str(doc.confluence.get("page_id"))
        if options.mode == "dry-run":
            if page_id:
                result.updated.append(
                    PublishItem(
                        path=doc.doc_path,
                        page_id=page_id,
                        space_id=doc.effective_space_id,
                        parent_page_id=parent_id,
                        reason="dry-run update",
                    )
                )
            else:
                result.created.append(
                    PublishItem(
                        path=doc.doc_path,
                        page_id=None,
                        space_id=doc.effective_space_id,
                        parent_page_id=parent_id,
                        reason="dry-run create",
                    )
                )
            return

        try:
            if page_id:
                self._update_existing_page(
                    doc=doc,
                    page_id=page_id,
                    parent_id=parent_id,
                    state=state,
                    options=options,
                    result=result,
                )
            else:
                self._create_new_page(doc=doc, parent_id=parent_id, state=state, result=result)
        except ConfluenceHTTPError as exc:
            detail = exc.response_body or str(exc)
            result.errors.append(PublishItem(path=doc.doc_path, page_id=page_id, error=f"http {exc.status_code}: {detail}"))
        except Exception as exc:
            result.errors.append(PublishItem(path=doc.doc_path, page_id=page_id, error=str(exc)))

    def _create_new_page(
        self,
        *,
        doc: ResolvedDoc,
        parent_id: str | None,
        state: PublishState,
        result: PublishResult,
    ) -> str:
        payload = {
            "spaceId": doc.effective_space_id,
            "status": _str(doc.confluence.get("status")) or "current",
            "title": doc.title,
            "body": {"representation": "storage", "value": markdown_to_storage(doc.body_markdown)},
        }
        if parent_id:
            payload["parentId"] = parent_id
        labels = doc.confluence.get("labels")
        if isinstance(labels, list) and labels:
            payload["labels"] = [{"name": item} for item in labels if isinstance(item, str) and item]

        created = self._client.post_json(path="/api/v2/pages", json_body=payload)
        new_page_id = _str(created.get("id"))
        if not new_page_id:
            raise ValueError(f"create returned empty page id for {doc.doc_path}")

        state.upsert(
            StateRecord(
                doc_path=doc.doc_path,
                page_id=new_page_id,
                content_hash=doc.content_hash,
                last_published_at=_now_iso(),
                last_published_version=_extract_version(created),
            )
        )
        self._doc_path_page_id[doc.doc_path] = new_page_id
        result.created.append(
            PublishItem(
                path=doc.doc_path,
                page_id=new_page_id,
                space_id=doc.effective_space_id,
                parent_page_id=parent_id,
            )
        )
        return new_page_id

    def _update_existing_page(
        self,
        *,
        doc: ResolvedDoc,
        page_id: str,
        parent_id: str | None,
        state: PublishState,
        options: PublishOptions,
        result: PublishResult,
    ) -> None:
        current = self._client.get_json(path=f"/api/v2/pages/{page_id}", params={"body-format": "storage"})
        current_space_id = _str(current.get("spaceId"))
        target_space_id = options.target_space_id or doc.effective_space_id
        if current_space_id and target_space_id and current_space_id != target_space_id:
            new_page_id = self._create_new_page(
                doc=doc,
                parent_id=parent_id,
                state=state,
                result=result,
            )
            self._page_id_remap[page_id] = new_page_id
            result.warnings.append(
                PublishItem(
                    path=doc.doc_path,
                    page_id=new_page_id,
                    space_id=doc.effective_space_id,
                    parent_page_id=parent_id,
                    warning="recreated in target space because existing page belonged to another space",
                )
            )
            return
        if options.safe_mode:
            drift = _has_drift(current_updated_at=_str(current.get("updatedAt")), state_record=state.get(doc.doc_path))
            if drift:
                message = "drift detected: remote updated after last_published_at"
                if options.fail_on_drift:
                    result.errors.append(PublishItem(path=doc.doc_path, page_id=page_id, error=message))
                else:
                    result.skipped.append(PublishItem(path=doc.doc_path, page_id=page_id, reason="drift"))
                    result.warnings.append(PublishItem(path=doc.doc_path, page_id=page_id, warning=message))
                return

        payload = {
            "id": page_id,
            "status": _str(current.get("status")) or "current",
            "title": doc.title,
            "spaceId": _str(current.get("spaceId")) or doc.effective_space_id,
            "body": {"representation": "storage", "value": markdown_to_storage(doc.body_markdown)},
            "version": {"number": _extract_version(current) + 1},
        }
        if parent_id and parent_id != page_id:
            payload["parentId"] = parent_id
        labels = doc.confluence.get("labels")
        if isinstance(labels, list) and labels:
            payload["labels"] = [{"name": item} for item in labels if isinstance(item, str) and item]

        try:
            updated = self._update_with_409_retry(page_id=page_id, payload=payload)
        except ConfluenceHTTPError as exc:
            # If parent was auto-resolved and Confluence rejects move due to hierarchy loop,
            # retry content update without changing parent relation.
            if (
                "parentId" in payload
                and doc.parent_source != "explicit"
                and _is_parent_loop_error(exc)
            ):
                if options.strict_parent_update and doc.doc_path != "_index.md":
                    raise
                fallback_payload = dict(payload)
                fallback_payload.pop("parentId", None)
                result.warnings.append(
                    PublishItem(
                        path=doc.doc_path,
                        page_id=page_id,
                        warning=(
                            "parent move skipped after hierarchy-loop error; "
                            "content updated without changing parent"
                        ),
                    )
                )
                updated = self._update_with_409_retry(page_id=page_id, payload=fallback_payload)
            else:
                raise
        state.upsert(
            StateRecord(
                doc_path=doc.doc_path,
                page_id=page_id,
                content_hash=doc.content_hash,
                last_published_at=_now_iso(),
                last_published_version=_extract_version(updated),
            )
        )
        self._doc_path_page_id[doc.doc_path] = page_id
        result.updated.append(
            PublishItem(
                path=doc.doc_path,
                page_id=page_id,
                space_id=doc.effective_space_id,
                parent_page_id=parent_id,
            )
        )

    def _resolve_parent_id(self, *, doc: ResolvedDoc, state: PublishState) -> str | None:
        parent_id = doc.resolved_parent_page_id
        if parent_id and parent_id in self._page_id_remap:
            parent_id = self._page_id_remap[parent_id]
        if parent_id:
            return parent_id
        parent_doc_path = doc.resolved_parent_doc_path
        if not parent_doc_path:
            return None
        mapped = self._doc_path_page_id.get(parent_doc_path)
        if mapped:
            return mapped
        record = state.get(parent_doc_path)
        if record and record.page_id:
            return self._page_id_remap.get(record.page_id, record.page_id)
        return None

    def _update_with_409_retry(self, *, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.put_json(path=f"/api/v2/pages/{page_id}", json_body=payload)
        except ConfluenceHTTPError as exc:
            if exc.status_code != 409:
                raise

        fresh = self._client.get_json(path=f"/api/v2/pages/{page_id}", params={"body-format": "storage"})
        retry_payload = dict(payload)
        retry_payload["version"] = {"number": _extract_version(fresh) + 1}
        return self._client.put_json(path=f"/api/v2/pages/{page_id}", json_body=retry_payload)

    def _delete_orphans(
        self,
        *,
        active_doc_paths: set[str],
        state: PublishState,
        options: PublishOptions,
        result: PublishResult,
    ) -> None:
        orphans = state.list_orphans(active_doc_paths=active_doc_paths)
        for record in orphans:
            if options.mode == "dry-run":
                result.updated.append(PublishItem(path=record.doc_path, page_id=record.page_id, reason="dry-run delete orphan"))
                continue
            try:
                self._client.delete_json(path=f"/api/v2/pages/{record.page_id}")
                state.remove(record.doc_path)
                result.updated.append(PublishItem(path=record.doc_path, page_id=record.page_id, reason="deleted orphan"))
            except ConfluenceHTTPError as exc:
                if exc.status_code == 404:
                    state.remove(record.doc_path)
                    result.warnings.append(
                        PublishItem(
                            path=record.doc_path,
                            page_id=record.page_id,
                            warning="orphan already absent in Confluence (404), removed from state",
                        )
                    )
                    continue
                result.errors.append(PublishItem(path=record.doc_path, page_id=record.page_id, error=f"delete failed: {exc}"))
            except Exception as exc:
                result.errors.append(PublishItem(path=record.doc_path, page_id=record.page_id, error=f"delete failed: {exc}"))


def markdown_to_storage(markdown_text: str) -> str:
    """
    Minimal deterministic converter for markdown -> Confluence storage.
    Supports headings (#, ##, ###) and paragraph blocks.
    """
    lines = markdown_text.splitlines()
    blocks: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            text = " ".join(part.strip() for part in para if part.strip())
            if text:
                blocks.append(f"<p>{html.escape(text)}</p>")
            para.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_para()
            continue
        if stripped.startswith("### "):
            flush_para()
            blocks.append(f"<h3>{html.escape(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            flush_para()
            blocks.append(f"<h2>{html.escape(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            flush_para()
            blocks.append(f"<h1>{html.escape(stripped[2:])}</h1>")
            continue
        para.append(stripped)

    flush_para()
    return "".join(blocks)


def _extract_storage_body(payload: dict[str, Any]) -> str:
    body = payload.get("body")
    if isinstance(body, dict):
        storage = body.get("storage")
        if isinstance(storage, dict):
            value = storage.get("value")
            if isinstance(value, str):
                return value
    return ""


def _extract_version(payload: dict[str, Any]) -> int:
    version = payload.get("version")
    if isinstance(version, dict):
        value = version.get("number")
        try:
            return int(value)
        except Exception:
            return 0
    try:
        return int(version)
    except Exception:
        return 0


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_parent_loop_error(exc: ConfluenceHTTPError) -> bool:
    text = " ".join(
        part.lower()
        for part in [str(exc), exc.response_body or ""]
        if isinstance(part, str)
    )
    return (
        "parent-child loop" in text
        or "can not set page as its own parent" in text
        or "cannot set page as its own parent" in text
    )


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_drift(*, current_updated_at: str | None, state_record: StateRecord | None) -> bool:
    if state_record is None:
        return False
    if not current_updated_at:
        return False
    left = _parse_dt(current_updated_at)
    right = _parse_dt(state_record.last_published_at)
    if left is None or right is None:
        return False
    return left > right


def _parse_dt(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    # handle patterns like 2026-03-09T10:11:12.000+0000
    if len(value) >= 5 and (value[-5] in {"+", "-"}) and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
