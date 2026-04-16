#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_QUESTION_STATUSES = ("accepted", "queued", "in_progress")
ACTIVE_DELIVERY_STATUSES = ("pending", "retry_scheduled", "in_progress")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_db_path_from_config(config_path: Path) -> Path:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    db_value = str(raw.get("database_path", "./bot.sqlite3")).strip() or "./bot.sqlite3"
    db_path = Path(db_value).expanduser()
    if not db_path.is_absolute():
        db_path = (config_path.parent / db_path).resolve()
    return db_path


def _count_one(cur: sqlite3.Cursor, sql: str, params: tuple[object, ...] = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def _snapshot(cur: sqlite3.Cursor, *, team_id: int | None) -> dict[str, int]:
    if team_id is None:
        return {
            "questions_accepted": _count_one(cur, "SELECT COUNT(1) FROM questions WHERE status = 'accepted'"),
            "questions_queued": _count_one(cur, "SELECT COUNT(1) FROM questions WHERE status = 'queued'"),
            "questions_in_progress": _count_one(cur, "SELECT COUNT(1) FROM questions WHERE status = 'in_progress'"),
            "qa_dispatch_bridge_rows": _count_one(cur, "SELECT COUNT(1) FROM qa_dispatch_bridge_state"),
            "event_deliveries_pending": _count_one(cur, "SELECT COUNT(1) FROM event_deliveries WHERE status = 'pending'"),
            "event_deliveries_retry_scheduled": _count_one(
                cur, "SELECT COUNT(1) FROM event_deliveries WHERE status = 'retry_scheduled'"
            ),
            "event_deliveries_in_progress": _count_one(
                cur, "SELECT COUNT(1) FROM event_deliveries WHERE status = 'in_progress'"
            ),
            "runtime_status_busy": _count_one(cur, "SELECT COUNT(1) FROM team_role_runtime_status WHERE status = 'busy'"),
            "runtime_status_free": _count_one(cur, "SELECT COUNT(1) FROM team_role_runtime_status WHERE status = 'free'"),
        }

    return {
        "questions_accepted": _count_one(
            cur, "SELECT COUNT(1) FROM questions WHERE team_id = ? AND status = 'accepted'", (team_id,)
        ),
        "questions_queued": _count_one(
            cur, "SELECT COUNT(1) FROM questions WHERE team_id = ? AND status = 'queued'", (team_id,)
        ),
        "questions_in_progress": _count_one(
            cur, "SELECT COUNT(1) FROM questions WHERE team_id = ? AND status = 'in_progress'", (team_id,)
        ),
        "qa_dispatch_bridge_rows": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM qa_dispatch_bridge_state s "
                "JOIN questions q ON q.question_id = s.question_id "
                "WHERE q.team_id = ?"
            ),
            (team_id,),
        ),
        "event_deliveries_pending": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM event_deliveries d "
                "JOIN thread_events e ON e.event_id = d.event_id "
                "WHERE e.team_id = ? AND d.status = 'pending'"
            ),
            (team_id,),
        ),
        "event_deliveries_retry_scheduled": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM event_deliveries d "
                "JOIN thread_events e ON e.event_id = d.event_id "
                "WHERE e.team_id = ? AND d.status = 'retry_scheduled'"
            ),
            (team_id,),
        ),
        "event_deliveries_in_progress": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM event_deliveries d "
                "JOIN thread_events e ON e.event_id = d.event_id "
                "WHERE e.team_id = ? AND d.status = 'in_progress'"
            ),
            (team_id,),
        ),
        "runtime_status_busy": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM team_role_runtime_status rs "
                "JOIN team_roles tr ON tr.team_role_id = rs.team_role_id "
                "WHERE tr.team_id = ? AND rs.status = 'busy'"
            ),
            (team_id,),
        ),
        "runtime_status_free": _count_one(
            cur,
            (
                "SELECT COUNT(1) "
                "FROM team_role_runtime_status rs "
                "JOIN team_roles tr ON tr.team_role_id = rs.team_role_id "
                "WHERE tr.team_id = ? AND rs.status = 'free'"
            ),
            (team_id,),
        ),
    }


def _print_snapshot(title: str, data: dict[str, int]) -> None:
    print(f"\n{title}")
    for key in sorted(data.keys()):
        print(f"  {key}: {data[key]}")


def _apply_reset(conn: sqlite3.Connection, *, team_id: int | None, now_ts: str) -> dict[str, int]:
    cur = conn.cursor()
    affected: dict[str, int] = {}

    if team_id is None:
        cur.execute(
            (
                "UPDATE questions "
                "SET status='cancelled', "
                "error_code='manual_prestart_recovery_reset', "
                "error_message='Cancelled by full_reset script', "
                "updated_at=? "
                "WHERE status IN ('accepted','queued','in_progress')"
            ),
            (now_ts,),
        )
        affected["questions_cancelled"] = int(cur.rowcount or 0)

        cur.execute(
            (
                "UPDATE qa_dispatch_bridge_state "
                "SET attempt_count=0, lease_expires_at=NULL, retry_not_before=NULL, "
                "last_error_code=NULL, last_error_message=NULL, updated_at=?"
            ),
            (now_ts,),
        )
        affected["qa_dispatch_bridge_rows_reset"] = int(cur.rowcount or 0)

        cur.execute("DELETE FROM event_deliveries WHERE status IN ('pending','retry_scheduled','in_progress')")
        affected["event_deliveries_deleted"] = int(cur.rowcount or 0)

        cur.execute(
            (
                "UPDATE team_role_runtime_status "
                "SET status='free', busy_request_id=NULL, busy_owner_user_id=NULL, busy_origin=NULL, "
                "preview_text=NULL, preview_source=NULL, busy_since=NULL, lease_expires_at=NULL, "
                "last_heartbeat_at=NULL, free_release_requested_at=NULL, free_release_delay_until=NULL, "
                "free_release_reason_pending=NULL, last_release_reason='manual_prestart_recovery_reset', "
                "status_version=status_version+1, updated_at=?"
            ),
            (now_ts,),
        )
        affected["runtime_status_rows_freed"] = int(cur.rowcount or 0)
        return affected

    cur.execute(
        (
            "UPDATE questions "
            "SET status='cancelled', "
            "error_code='manual_prestart_recovery_reset', "
            "error_message='Cancelled by full_reset script', "
            "updated_at=? "
            "WHERE team_id=? AND status IN ('accepted','queued','in_progress')"
        ),
        (now_ts, team_id),
    )
    affected["questions_cancelled"] = int(cur.rowcount or 0)

    cur.execute(
        (
            "UPDATE qa_dispatch_bridge_state "
            "SET attempt_count=0, lease_expires_at=NULL, retry_not_before=NULL, "
            "last_error_code=NULL, last_error_message=NULL, updated_at=? "
            "WHERE question_id IN (SELECT question_id FROM questions WHERE team_id=?)"
        ),
        (now_ts, team_id),
    )
    affected["qa_dispatch_bridge_rows_reset"] = int(cur.rowcount or 0)

    cur.execute(
        (
            "DELETE FROM event_deliveries "
            "WHERE status IN ('pending','retry_scheduled','in_progress') "
            "AND event_id IN (SELECT event_id FROM thread_events WHERE team_id=?)"
        ),
        (team_id,),
    )
    affected["event_deliveries_deleted"] = int(cur.rowcount or 0)

    cur.execute(
        (
            "UPDATE team_role_runtime_status "
            "SET status='free', busy_request_id=NULL, busy_owner_user_id=NULL, busy_origin=NULL, "
            "preview_text=NULL, preview_source=NULL, busy_since=NULL, lease_expires_at=NULL, "
            "last_heartbeat_at=NULL, free_release_requested_at=NULL, free_release_delay_until=NULL, "
            "free_release_reason_pending=NULL, last_release_reason='manual_prestart_recovery_reset', "
            "status_version=status_version+1, updated_at=? "
            "WHERE team_role_id IN (SELECT team_role_id FROM team_roles WHERE team_id=?)"
        ),
        (now_ts, team_id),
    )
    affected["runtime_status_rows_freed"] = int(cur.rowcount or 0)
    return affected


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prestart full reset of runtime/queue activity in SQLite database."
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (used when --db is not provided). Default: config.json",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Direct path to sqlite DB. Overrides --config.database_path.",
    )
    parser.add_argument(
        "--team-id",
        type=int,
        default=None,
        help="Optional team scope. If omitted, reset is global.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag script runs in dry-run mode.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backup before apply.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    else:
        if not config_path.exists():
            print(f"ERROR: config file not found: {config_path}")
            return 2
        db_path = _load_db_path_from_config(config_path)
    if not db_path.exists():
        print(f"ERROR: database file not found: {db_path}")
        return 2

    team_id = int(args.team_id) if args.team_id is not None else None
    mode = "TEAM" if team_id is not None else "GLOBAL"

    print(f"DB: {db_path}")
    print(f"SCOPE: {mode}" + (f" (team_id={team_id})" if team_id is not None else ""))
    print("MODE: APPLY" if args.apply else "MODE: DRY-RUN")
    print("\nIMPORTANT: run only when services are stopped.")

    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        cur = conn.cursor()
        before = _snapshot(cur, team_id=team_id)
        _print_snapshot("Before", before)

        if not args.apply:
            print("\nDry-run complete. No changes applied.")
            return 0

        if not args.no_backup:
            backup_path = db_path.with_suffix(db_path.suffix + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            shutil.copy2(db_path, backup_path)
            print(f"\nBackup created: {backup_path}")

        now_ts = _utc_now()
        conn.execute("BEGIN IMMEDIATE")
        affected = _apply_reset(conn, team_id=team_id, now_ts=now_ts)
        conn.execute("COMMIT")

        after = _snapshot(cur, team_id=team_id)
        _print_snapshot("After", after)
        print("\nAffected rows")
        for key in sorted(affected.keys()):
            print(f"  {key}: {affected[key]}")
        print("\nReset complete.")
        return 0
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"ERROR: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

