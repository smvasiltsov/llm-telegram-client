# Plan Supervisor Contract (Step 1)

## Tool ID
- `plan.supervisor`

## Commands
- `start_plan`
- `get_status`
- `report_step`
- `request_approval`
- `approve_next`
- `reject_step`

## Common Envelope
```json
{
  "command": "<command>",
  "plan_run_id": "plan_...",
  "team_id": 112,
  "thread_id": "thread_...",
  "actor_role": "codex",
  "payload": {}
}
```

## Payloads

### `start_plan`
```json
{
  "goal": "string",
  "steps": [
    {"step_id": "s1", "title": "string", "description": "string", "order": 1}
  ],
  "require_manual_approval": true
}
```

### `report_step`
```json
{
  "step_id": "s1",
  "summary": "what was done",
  "artifacts": [{"type": "file|link|log", "ref": "string"}],
  "test_commands": ["pytest -q"],
  "result": "done|blocked"
}
```

### `request_approval`
```json
{
  "step_id": "s1",
  "note": "ready for approval"
}
```

### `approve_next`
```json
{
  "step_id": "s1",
  "decision": "approved",
  "comment": "optional"
}
```

### `reject_step`
```json
{
  "step_id": "s1",
  "decision": "rejected",
  "comment": "what to fix"
}
```

### `get_status`
```json
{
  "include_events": true
}
```

## Step Statuses
- `pending`
- `in_progress`
- `reported`
- `approval_requested`
- `approved`
- `rejected`
- `done`
- `blocked`

## Plan Statuses
- `active`
- `completed`
- `failed`
- `cancelled`

## FSM Transitions
- `pending -> in_progress` (when current step is issued)
- `in_progress -> reported` (`report_step`, `result=done`)
- `in_progress -> blocked` (`report_step`, `result=blocked`)
- `reported -> approval_requested` (`request_approval`)
- `approval_requested -> approved` (`approve_next`)
- `approval_requested -> rejected` (`reject_step`)
- `approved -> done` (step closed)
- `rejected -> in_progress` (rework)
- `blocked -> in_progress` (after unblock)

## Command Preconditions
- Only one `in_progress` step per `plan_run_id`.
- `approve_next/reject_step` allowed only from `approval_requested`.
- Next step can start only when previous is `done`.

## Command Results (shape)
```json
{
  "ok": true,
  "plan_run_id": "plan_...",
  "plan_status": "active",
  "current_step_id": "s2",
  "steps": [
    {"step_id": "s1", "status": "done"},
    {"step_id": "s2", "status": "in_progress"}
  ],
  "ui_event_emitted": true
}
```
