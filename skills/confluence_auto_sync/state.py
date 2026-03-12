from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StateRecord:
    doc_path: str
    page_id: str
    content_hash: str
    last_published_at: str
    last_published_version: int

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StateRecord | None:
        doc_path = data.get("doc_path")
        page_id = data.get("page_id")
        content_hash = data.get("content_hash")
        last_published_at = data.get("last_published_at")
        version_raw = data.get("last_published_version")

        if not isinstance(doc_path, str) or not doc_path.strip():
            return None
        if not isinstance(page_id, str) or not page_id.strip():
            return None
        if not isinstance(content_hash, str) or not content_hash.strip():
            return None
        if not isinstance(last_published_at, str) or not last_published_at.strip():
            return None
        try:
            version = int(version_raw)
        except Exception:
            return None
        if version < 0:
            return None

        return StateRecord(
            doc_path=doc_path.strip(),
            page_id=page_id.strip(),
            content_hash=content_hash.strip(),
            last_published_at=last_published_at.strip(),
            last_published_version=version,
        )


@dataclass(frozen=True)
class StateSummary:
    total_records: int
    with_page_id: int
    with_content_hash: int


class PublishState:
    def __init__(self, *, state_path: Path, records: dict[str, StateRecord] | None = None) -> None:
        self._state_path = state_path
        self._records: dict[str, StateRecord] = records or {}

    @property
    def state_path(self) -> Path:
        return self._state_path

    @property
    def records(self) -> dict[str, StateRecord]:
        return dict(self._records)

    def get(self, doc_path: str) -> StateRecord | None:
        return self._records.get(doc_path)

    def has(self, doc_path: str) -> bool:
        return doc_path in self._records

    def upsert(self, record: StateRecord) -> None:
        self._records[record.doc_path] = record

    def remove(self, doc_path: str) -> bool:
        return self._records.pop(doc_path, None) is not None

    def changed(self, *, doc_path: str, content_hash: str, changed_only: bool, update_if_changed_only: bool) -> bool:
        existing = self.get(doc_path)
        if existing is None:
            return True
        if not changed_only and not update_if_changed_only:
            return True
        return existing.content_hash != content_hash

    def snapshot_summary(self) -> StateSummary:
        total = len(self._records)
        with_page = sum(1 for item in self._records.values() if item.page_id)
        with_hash = sum(1 for item in self._records.values() if item.content_hash)
        return StateSummary(total_records=total, with_page_id=with_page, with_content_hash=with_hash)

    def list_orphans(self, active_doc_paths: set[str]) -> list[StateRecord]:
        return [record for path, record in self._records.items() if path not in active_doc_paths]

    def to_json_dict(self) -> dict[str, Any]:
        ordered = [asdict(record) for record in sorted(self._records.values(), key=lambda item: item.doc_path)]
        return {"version": 1, "records": ordered}

    def save(self) -> None:
        payload = self.to_json_dict()
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
        self._state_path.write_text(f"{text}\n", encoding="utf-8")


def load_publish_state(state_path: str | Path) -> PublishState:
    path = Path(state_path).expanduser()
    if not path.exists() or not path.is_file():
        return PublishState(state_path=path, records={})

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid state JSON at {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"state file must be JSON object: {path}")

    raw_records = raw.get("records")
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        raise ValueError(f"state.records must be an array: {path}")

    records: dict[str, StateRecord] = {}
    for idx, item in enumerate(raw_records):
        if not isinstance(item, dict):
            raise ValueError(f"state.records[{idx}] must be object: {path}")
        record = StateRecord.from_dict(item)
        if record is None:
            raise ValueError(f"state.records[{idx}] has invalid schema: {path}")
        records[record.doc_path] = record

    return PublishState(state_path=path, records=records)
