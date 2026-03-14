#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_config


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def _count(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _read_catalog_role_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        role_name = str(payload.get("role_name", "")).strip().lower()
        if role_name:
            names.add(role_name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description="Print rollout readiness for LTC-12 JSON master-role mode.")
    parser.add_argument("--config", default="config.json", help="Path to bot config file")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(json.dumps({"ok": False, "error": f"Config not found: {config_path}"}, ensure_ascii=False))
        return 2
    config = load_config(config_path)

    db_path = Path(config.database_path)
    if not db_path.is_absolute():
        db_path = (config_path.parent / db_path).resolve()
    if not db_path.exists():
        print(json.dumps({"ok": False, "error": f"DB not found: {db_path}"}, ensure_ascii=False))
        return 2

    roles_catalog_dir = (config_path.parent / "roles_catalog").resolve()
    export_marker = roles_catalog_dir / ".migration" / "db_export_v1.done.json"
    catalog_role_names = _read_catalog_role_names(roles_catalog_dir) if roles_catalog_dir.exists() else set()

    conn = sqlite3.connect(str(db_path))
    try:
        required_tables = ["team_roles", "provider_user_data", "roles"]
        required_columns = [
            ("team_roles", "team_role_id"),
            ("team_roles", "role_name"),
            ("provider_user_data", "role_name"),
        ]
        missing_tables = [name for name in required_tables if not _has_table(conn, name)]
        missing_columns = [f"{t}:{c}" for t, c in required_columns if _has_table(conn, t) and not _has_column(conn, t, c)]

        counts = {
            "catalog_files": len(list(roles_catalog_dir.glob("*.json"))) if roles_catalog_dir.exists() else 0,
            "catalog_roles": len(catalog_role_names),
            "active_team_roles": _count(conn, "SELECT COUNT(*) FROM team_roles WHERE is_active = 1")
            if _has_table(conn, "team_roles")
            else 0,
            "active_team_roles_missing_role_name": _count(
                conn,
                "SELECT COUNT(*) FROM team_roles WHERE is_active = 1 AND (role_name IS NULL OR trim(role_name) = '')",
            )
            if _has_table(conn, "team_roles") and _has_column(conn, "team_roles", "role_name")
            else 0,
            "provider_role_scoped_missing_role_name": _count(
                conn,
                "SELECT COUNT(*) FROM provider_user_data WHERE role_id IS NOT NULL AND (role_name IS NULL OR trim(role_name) = '')",
            )
            if _has_table(conn, "provider_user_data") and _has_column(conn, "provider_user_data", "role_name")
            else 0,
            "active_team_roles_not_in_catalog": 0,
        }

        if _has_table(conn, "team_roles") and _has_column(conn, "team_roles", "role_name") and catalog_role_names:
            # SQLite IN with dynamic list is cumbersome without temp table; compute in Python reliably.
            rows = conn.execute(
                """
                SELECT lower(role_name)
                FROM team_roles
                WHERE is_active = 1 AND role_name IS NOT NULL AND trim(role_name) <> ''
                """
            ).fetchall()
            counts["active_team_roles_not_in_catalog"] = sum(1 for row in rows if str(row[0]) not in catalog_role_names)
        elif _has_table(conn, "team_roles") and _has_column(conn, "team_roles", "role_name"):
            counts["active_team_roles_not_in_catalog"] = _count(
                conn,
                "SELECT COUNT(*) FROM team_roles WHERE is_active = 1 AND role_name IS NOT NULL AND trim(role_name) <> ''",
            )

        checks = {
            "schema_ok": not missing_tables and not missing_columns,
            "roles_catalog_exists": roles_catalog_dir.exists(),
            "roles_catalog_non_empty": counts["catalog_roles"] > 0,
            "export_marker_exists": export_marker.exists(),
            "active_team_roles_have_role_name": counts["active_team_roles_missing_role_name"] == 0,
            "provider_role_scoped_has_role_name": counts["provider_role_scoped_missing_role_name"] == 0,
            "team_roles_resolved_in_catalog": counts["active_team_roles_not_in_catalog"] == 0,
        }
        ok = all(checks.values())
        payload = {
            "ok": ok,
            "config_path": str(config_path),
            "database_path": str(db_path),
            "roles_catalog_dir": str(roles_catalog_dir),
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "counts": counts,
            "checks": checks,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
