from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.storage import Storage


ROLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class RoleCatalogExportResult:
    marker_created: bool
    skipped_by_marker: bool
    exported_count: int
    conflict_count: int
    invalid_count: int
    report_path: Path
    conflict_log_path: Path


def export_roles_from_db_first_run(storage: Storage, root_dir: str | Path) -> RoleCatalogExportResult:
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)
    migration_dir = root / ".migration"
    migration_dir.mkdir(parents=True, exist_ok=True)
    marker_path = migration_dir / "db_export_v1.done.json"
    report_path = migration_dir / "db_export_v1_report.json"
    conflict_log_path = migration_dir / "db_export_v1_conflicts.jsonl"

    if marker_path.exists():
        return RoleCatalogExportResult(
            marker_created=False,
            skipped_by_marker=True,
            exported_count=0,
            conflict_count=0,
            invalid_count=0,
            report_path=report_path,
            conflict_log_path=conflict_log_path,
        )

    exported_count = 0
    conflict_count = 0
    invalid_count = 0
    now = datetime.now(timezone.utc).isoformat()
    logger = logging.getLogger("bot")

    if storage.has_legacy_roles_table():
        for role in storage.list_roles():
            role_name = str(role.role_name or "").strip().lower()
            if not role_name or not ROLE_NAME_RE.match(role_name):
                _append_jsonl(
                    conflict_log_path,
                    {
                        "event": "invalid_role_name",
                        "role_id": role.role_id,
                        "role_name": role.role_name,
                        "normalized_role_name": role_name,
                        "ts": now,
                    },
                )
                invalid_count += 1
                continue

            role_path = root / f"{role_name}.json"
            if role_path.exists():
                _append_jsonl(
                    conflict_log_path,
                    {
                        "event": "conflict_existing_json",
                        "role_id": role.role_id,
                        "role_name": role_name,
                        "json_path": str(role_path),
                        "ts": now,
                    },
                )
                conflict_count += 1
                continue

            payload = {
                "schema_version": 1,
                "role_name": role_name,
                "description": role.description,
                "base_system_prompt": role.base_system_prompt,
                "extra_instruction": role.extra_instruction,
                "llm_model": role.llm_model,
                "is_active": role.is_active,
            }
            role_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            exported_count += 1

    report = {
        "version": 1,
        "started_at": now,
        "exported_count": exported_count,
        "conflict_count": conflict_count,
        "invalid_count": invalid_count,
        "roles_table_present": storage.has_legacy_roles_table(),
        "root_dir": str(root.resolve()),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    marker_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if conflict_count or invalid_count:
        logger.warning(
            "role catalog export conflicts detected: conflicts=%s invalid=%s path=%s",
            conflict_count,
            invalid_count,
            conflict_log_path,
        )
    logger.info(
        "role catalog export done: exported=%s conflicts=%s invalid=%s marker=%s",
        exported_count,
        conflict_count,
        invalid_count,
        marker_path,
    )
    return RoleCatalogExportResult(
        marker_created=True,
        skipped_by_marker=False,
        exported_count=exported_count,
        conflict_count=conflict_count,
        invalid_count=invalid_count,
        report_path=report_path,
        conflict_log_path=conflict_log_path,
    )


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
