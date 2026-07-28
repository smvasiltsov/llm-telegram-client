# Plan Supervisor Storage Design (Step 2)

## Goal
Stateful SQLite storage for `plan.supervisor` with additive migration and repository methods in `app/storage.py`.

## Tables

### 1) `plan_runs`
```sql
CREATE TABLE IF NOT EXISTS plan_runs (
    plan_run_id TEXT PRIMARY KEY,
    team_id INTEGER NOT NULL,
    thread_id TEXT NOT NULL,
    created_by_user_id INTEGER,
    actor_role TEXT,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    require_manual_approval INTEGER NOT NULL DEFAULT 1,
    current_step_order INTEGER,
    current_step_id TEXT,
    total_steps INTEGER NOT NULL,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    failed_step_id TEXT,
    cancelled_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (team_id) REFERENCES teams(team_id),
    CHECK (status IN ('active','completed','failed','cancelled'))
);
```

### 2) `plan_steps`
```sql
CREATE TABLE IF NOT EXISTS plan_steps (
    plan_run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    artifacts_json TEXT,
    test_commands_json TEXT,
    assignee_role TEXT,
    started_at TEXT,
    reported_at TEXT,
    approved_at TEXT,
    done_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (plan_run_id, step_id),
    FOREIGN KEY (plan_run_id) REFERENCES plan_runs(plan_run_id),
    CHECK (status IN (
        'pending','in_progress','reported','approval_requested',
        'approved','rejected','done','blocked'
    ))
);
```

### 3) `plan_events`
```sql
CREATE TABLE IF NOT EXISTS plan_events (
    event_id TEXT PRIMARY KEY,
    plan_run_id TEXT NOT NULL,
    step_id TEXT,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    payload_json TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (plan_run_id) REFERENCES plan_runs(plan_run_id),
    FOREIGN KEY (plan_run_id, step_id) REFERENCES plan_steps(plan_run_id, step_id)
);
```

### 4) `plan_gates` (extensibility)
```sql
CREATE TABLE IF NOT EXISTS plan_gates (
    gate_id TEXT PRIMARY KEY,
    plan_run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    gate_type TEXT NOT NULL,
    status TEXT NOT NULL,
    checker_role TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plan_run_id, step_id) REFERENCES plan_steps(plan_run_id, step_id),
    CHECK (status IN ('pending','running','passed','failed','skipped'))
);
```

## Indexes
```sql
CREATE INDEX IF NOT EXISTS idx_plan_runs_team_updated
ON plan_runs(team_id, updated_at DESC, plan_run_id DESC);

CREATE INDEX IF NOT EXISTS idx_plan_runs_thread_updated
ON plan_runs(thread_id, updated_at DESC, plan_run_id DESC);

CREATE INDEX IF NOT EXISTS idx_plan_runs_status_updated
ON plan_runs(status, updated_at DESC, plan_run_id DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_steps_order
ON plan_steps(plan_run_id, step_order);

CREATE INDEX IF NOT EXISTS idx_plan_steps_status_order
ON plan_steps(plan_run_id, status, step_order);

CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_events_idempotency
ON plan_events(idempotency_key)
WHERE idempotency_key IS NOT NULL AND idempotency_key <> '';

CREATE INDEX IF NOT EXISTS idx_plan_events_run_created
ON plan_events(plan_run_id, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_plan_events_step_created
ON plan_events(plan_run_id, step_id, created_at DESC, event_id DESC);

CREATE INDEX IF NOT EXISTS idx_plan_gates_run_step
ON plan_gates(plan_run_id, step_id, status, updated_at DESC);
```

## Migration Strategy (additive)
1. In `Storage._init_schema()`: create tables/indexes with `IF NOT EXISTS`.
2. Add `_migrate_plan_supervisor_additive()` and call after existing migrations.
3. Backfill only if needed:
   - no destructive rename/drop;
   - no impact on legacy QA/thread_events data.
4. Transaction: migration in one DB transaction + commit.

Suggested call site in `Storage._init_schema()`:
- after `self._migrate_role_runtime_status_additive()`
- before final `_conn.commit()`.

## Repository Methods (Storage)

### plan_runs
- `create_plan_run(...) -> PlanRun`
- `get_plan_run(plan_run_id: str) -> PlanRun | None`
- `list_plan_runs(team_id: int | None, thread_id: str | None, status: str | None, limit: int = 100) -> list[PlanRun]`
- `update_plan_run_status(plan_run_id: str, status: str, *, failed_step_id: str | None = None, cancelled_reason: str | None = None) -> PlanRun`
- `set_plan_run_current_step(plan_run_id: str, step_id: str | None, step_order: int | None) -> None`

### plan_steps
- `create_plan_steps(plan_run_id: str, items: list[tuple[str,int,str,str|None]]) -> list[PlanStep]`
- `get_plan_step(plan_run_id: str, step_id: str) -> PlanStep | None`
- `list_plan_steps(plan_run_id: str) -> list[PlanStep]`
- `set_plan_step_status(plan_run_id: str, step_id: str, to_status: str, *, summary: str | None = None, artifacts_json: str | None = None, test_commands_json: str | None = None) -> PlanStep`
- `get_current_plan_step(plan_run_id: str) -> PlanStep | None`

### plan_events
- `create_plan_event(...) -> PlanEvent` (idempotent by `idempotency_key`)
- `list_plan_events(plan_run_id: str, step_id: str | None = None, limit: int = 200) -> list[PlanEvent]`

### plan_gates (optional v1.1)
- `upsert_plan_gate(...) -> PlanGate`
- `list_plan_gates(plan_run_id: str, step_id: str | None = None) -> list[PlanGate]`

## Write/UoW Rules
- All mutating methods use `_require_write_transaction(...)`.
- State transitions validated in application service (`PlanSupervisorService`), storage layer enforces persistence + integrity.

## DTO Additions (`app/models.py`)
- `PlanRun`
- `PlanStep`
- `PlanEvent`
- `PlanGate`

## API Projection Read Model
Target projection query shape for widget:
- plan header (`plan_runs`)
- ordered steps (`plan_steps ORDER BY step_order`)
- latest events (`plan_events`)
- optional gate summaries (`plan_gates`)

One-shot method suggestion:
- `get_plan_run_view(plan_run_id: str) -> dict[str, object]`
