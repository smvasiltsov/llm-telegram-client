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


def _count_table(conn: sqlite3.Connection, table: str) -> int | None:
    if not _has_table(conn, table):
        return None
    return _count(conn, f"SELECT COUNT(*) FROM {table}")


def _count_nulls(conn: sqlite3.Connection, table: str, column: str) -> int | None:
    if not _has_table(conn, table) or not _has_column(conn, table, column):
        return None
    return _count(conn, f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print rollout readiness for pure team mode.")
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

    conn = sqlite3.connect(str(db_path))
    try:
        required_tables = [
            "teams",
            "team_bindings",
            "team_roles",
            "user_role_sessions",
            "role_prepost_processing",
            "role_skills_enabled",
            "pending_messages",
            "pending_user_fields",
        ]
        forbidden_tables = ["groups", "group_roles"]
        required_columns = [
            ("team_roles", "team_role_id"),
            ("team_roles", "extra_instruction_override"),
            ("user_role_sessions", "team_id"),
            ("user_role_sessions", "team_role_id"),
            ("role_prepost_processing", "team_id"),
            ("role_prepost_processing", "team_role_id"),
            ("role_skills_enabled", "team_id"),
            ("role_skills_enabled", "team_role_id"),
            ("pending_messages", "team_id"),
            ("pending_user_fields", "team_id"),
        ]
        forbidden_columns = [
            ("user_role_sessions", "group_id"),
            ("role_prepost_processing", "group_id"),
            ("role_skills_enabled", "group_id"),
        ]
        missing_tables = [name for name in required_tables if not _has_table(conn, name)]
        missing_columns = [f"{table}:{column}" for table, column in required_columns if not _has_column(conn, table, column)]
        legacy_tables_present = [name for name in forbidden_tables if _has_table(conn, name)]
        legacy_columns_present = [
            f"{table}:{column}" for table, column in forbidden_columns if _has_table(conn, table) and _has_column(conn, table, column)
        ]

        team_bindings_telegram = (
            _count(conn, "SELECT COUNT(*) FROM team_bindings WHERE interface_type = 'telegram'")
            if _has_table(conn, "team_bindings")
            else None
        )
        counts = {
            "teams": _count_table(conn, "teams"),
            "team_bindings_telegram": team_bindings_telegram,
            "team_roles": _count_table(conn, "team_roles"),
            "team_roles_without_team_role_id": _count_nulls(conn, "team_roles", "team_role_id"),
            "sessions_total": _count_table(conn, "user_role_sessions"),
            "sessions_without_team_id": _count_nulls(conn, "user_role_sessions", "team_id"),
            "sessions_without_team_role_id": _count_nulls(conn, "user_role_sessions", "team_role_id"),
            "prepost_total": _count_table(conn, "role_prepost_processing"),
            "prepost_without_team_id": _count_nulls(conn, "role_prepost_processing", "team_id"),
            "prepost_without_team_role_id": _count_nulls(conn, "role_prepost_processing", "team_role_id"),
            "skills_total": _count_table(conn, "role_skills_enabled"),
            "skills_without_team_id": _count_nulls(conn, "role_skills_enabled", "team_id"),
            "skills_without_team_role_id": _count_nulls(conn, "role_skills_enabled", "team_role_id"),
            "pending_total": _count_table(conn, "pending_messages"),
            "pending_without_team_id": _count_nulls(conn, "pending_messages", "team_id"),
            "pending_user_fields_total": _count_table(conn, "pending_user_fields"),
            "pending_user_fields_without_team_id": _count_nulls(conn, "pending_user_fields", "team_id"),
        }

        def _is_zero(value: int | None) -> bool:
            return value == 0

        checks = {
            "schema_ok": not missing_tables and not missing_columns,
            "legacy_tables_removed": not legacy_tables_present,
            "legacy_columns_removed": not legacy_columns_present,
            "team_roles_have_surrogate_id": _is_zero(counts["team_roles_without_team_role_id"]),
            "sessions_team_scoped": _is_zero(counts["sessions_without_team_id"]),
            "sessions_have_team_role_id": _is_zero(counts["sessions_without_team_role_id"]),
            "prepost_team_scoped": _is_zero(counts["prepost_without_team_id"]),
            "prepost_have_team_role_id": _is_zero(counts["prepost_without_team_role_id"]),
            "skills_team_scoped": _is_zero(counts["skills_without_team_id"]),
            "skills_have_team_role_id": _is_zero(counts["skills_without_team_role_id"]),
            "pending_team_scoped": _is_zero(counts["pending_without_team_id"]),
            "pending_user_fields_team_scoped": _is_zero(counts["pending_user_fields_without_team_id"]),
        }
        ok = all(checks.values())

        payload = {
            "ok": ok,
            "config_path": str(config_path),
            "database_path": str(db_path),
            "rollout_mode": config.team_rollout_mode,
            "dual_read_enabled": config.team_dual_read_enabled,
            "dual_write_enabled": config.team_dual_write_enabled,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "legacy_tables_present": legacy_tables_present,
            "legacy_columns_present": legacy_columns_present,
            "counts": counts,
            "checks": checks,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
