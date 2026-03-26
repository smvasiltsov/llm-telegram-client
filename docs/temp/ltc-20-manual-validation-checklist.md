# LTC-20 Manual Validation Checklist

## 1) Config and Startup
- Set `runtime_status.free_transition_delay_sec` in `config.json` to non-zero (for example `30`).
- Restart bot on existing DB.
- Confirm startup has no `OperationalError` related to `free_release_delay_until` index/column.

## 2) Delayed Free Semantics
- Trigger role request from group/private flow.
- While request is in-flight, role is `BUSY`.
- After response delivery, role remains `BUSY` during configured delay.
- After delay timeout, role transitions to `FREE`.

## 3) Busy Preview During Delay
- While delayed-release window is active, open role card/status view.
- Confirm preview is preserved and visible until final transition to `FREE`.
- Confirm preview is cleared after final `FREE`.

## 4) Retry/Failure Paths
- Simulate `llm_failed_no_retry` path.
- Confirm role still stays `BUSY` for delay window before final `FREE`.
- Confirm `delivery_failed` follows same behavior.

## 5) Regression Smoke
- `/groups` and `/roles` callbacks still work.
- Role invocation/routing unchanged except delayed `FREE`.
- Session reset and auth/pending flows are not regressed.
