# Full Reset

`full_reset.py` is a prestart recovery utility for SQLite state.

Use it when runtime gets stuck in loops or stale activity and API reset is not enough.

## What it resets

- `questions` in `accepted/queued/in_progress` -> `cancelled`
- `qa_dispatch_bridge_state` attempt/lease/retry/error fields
- active `event_deliveries` in `pending/retry_scheduled/in_progress` (deleted)
- `team_role_runtime_status` -> `free` + busy/lease fields cleared

By default it works globally. You can scope by `--team-id`.

## Important

Stop all services before running:

```bash
sudo systemctl stop telegram_service api_service runtime_service
```

Run script from repository root:

```bash
python3 full_reset/full_reset.py --config config.json
```

This is dry-run mode (no changes).

## Apply mode

Global apply:

```bash
python3 full_reset/full_reset.py --config config.json --apply
```

Team-only apply:

```bash
python3 full_reset/full_reset.py --config config.json --team-id 123 --apply
```

Script creates DB backup automatically in apply mode:

`<db_path>.bak.YYYYMMDD_HHMMSS`

To disable backup:

```bash
python3 full_reset/full_reset.py --config config.json --apply --no-backup
```

## Explicit DB path

If needed, bypass config:

```bash
python3 full_reset/full_reset.py --db /absolute/path/to/bot.sqlite3 --apply
```

## Start services after reset

```bash
sudo systemctl start runtime_service api_service telegram_service
```

