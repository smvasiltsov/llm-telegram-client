#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.storage import Storage


def _parse_expect_column(raw: str) -> tuple[str, str]:
    parts = raw.split(":", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError(f"Invalid --expect-column value: {raw!r}. Expected format table:column")
    return parts[0].strip(), parts[1].strip()


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,))
    return cur.fetchone() is not None


def _list_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in cur.fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run storage migrations on a copied SQLite DB and verify expected schema items."
    )
    parser.add_argument("--db-path", default="bot.sqlite3", help="Path to source SQLite DB")
    parser.add_argument("--expect-table", action="append", default=[], help="Table name expected after migration")
    parser.add_argument(
        "--expect-column",
        action="append",
        default=[],
        help="Expected column in format table:column (repeatable)",
    )
    args = parser.parse_args()

    source_path = Path(args.db_path).resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": f"DB file not found: {source_path}"}, ensure_ascii=False))
        return 2

    with tempfile.TemporaryDirectory(prefix="db-migration-smoke-") as td:
        smoke_db = Path(td) / source_path.name
        shutil.copy2(source_path, smoke_db)

        # Instantiating Storage runs schema init and in-code migrations.
        _ = Storage(smoke_db)
        conn = sqlite3.connect(str(smoke_db))
        try:
            missing_tables: list[str] = []
            missing_columns: list[str] = []

            for table in args.expect_table:
                if not _has_table(conn, table):
                    missing_tables.append(table)

            for raw in args.expect_column:
                table, column = _parse_expect_column(raw)
                if not _has_table(conn, table):
                    missing_columns.append(f"{table}:{column} (table missing)")
                    continue
                if column not in _list_columns(conn, table):
                    missing_columns.append(f"{table}:{column}")

            ok = not missing_tables and not missing_columns
            result = {
                "ok": ok,
                "source_db": str(source_path),
                "smoke_db": str(smoke_db),
                "missing_tables": missing_tables,
                "missing_columns": missing_columns,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        finally:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
