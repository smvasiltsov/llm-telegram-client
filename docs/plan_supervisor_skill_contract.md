# Plan Supervisor Skill Contract (Step 1)

## Identity
- `skill_id`: `plan_supervisor`
- skill type: model-callable `skills/*` (not `app/tools/*`)

## Supported Operations (MVP)
1. `start_plan`
2. `get_status`
3. `report_step`
4. `request_approval`
5. `approve_next`
6. `reject_step`

## Primary Input Contract
Top-level format:
```json
{
  "operation": "<one_of_supported_operations>",
  "payload": {"...": "operation specific"},
  "team_id": 112,
  "thread_id": "thread_123"
}
```

Rules:
- `operation` is required.
- `payload` is required for all operations except `get_status` (may be `{}`).
- `team_id/thread_id` priority: explicit args > context fallback.

## Legacy Compatibility Adapter
Legacy format allowed:
```json
{
  "command": "<legacy_operation_name>",
  "payload": {"...": "same payload"}
}
```

Normalization rules:
- if `operation` missing and `command` present -> use `operation=command`.
- if both present and equal -> OK.
- if both present and different -> validation error.
- if neither present -> validation error.

## Operation Payloads

### `start_plan`
```json
{
  "goal": "string",
  "steps": [
    {"step_id": "s1", "title": "string", "description": "string"}
  ],
  "require_manual_approval": true
}
```

### `get_status`
```json
{}
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
  "comment": "optional"
}
```

### `reject_step`
```json
{
  "step_id": "s1",
  "comment": "what to fix"
}
```

## Output Contract
`SkillResult.output` shape:
```json
{
  "type": "plan_supervisor_result",
  "operation": "<resolved_operation>",
  "result": {
    "plan_run": {"...": "current plan state"},
    "steps": [{"...": "ordered step state"}],
    "events": [{"...": "plan events"}],
    "ui": {
      "progress_total": 0,
      "progress_done": 0,
      "progress_percent": 0,
      "current_step_id": "s1"
    }
  }
}
```

## Validation Errors
- unknown/unsupported operation
- payload schema mismatch
- conflicting `operation` and `command`
- missing required fields
- invalid FSM transition (delegated from `PlanSupervisorService`)
