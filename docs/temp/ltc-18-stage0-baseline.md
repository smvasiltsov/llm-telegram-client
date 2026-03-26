# LTC-18 Stage 0 Baseline and Safety-Net

## Goal
Prepare a safe implementation path for real-time role runtime status (`free`/`busy`) with a single source of truth shared by runtime and admin UI.

## Confirmed Requirements
- Default occupancy unit is `team_role` (`team_role_id`).
- Busy/free source must be unified for orchestrator/runtime and admin UI.
- Busy is set at the moment of sending request to LLM.
- Free is set only after LLM response is delivered to user.
- Skill/tool/post-processing executes inside busy window.
- Retry after timeout/failure keeps busy.
- If request is not auto-forwarded/retried to LLM after timeout/failure, status becomes free.
- Preview length is 100 chars.
- Preview source is only user text or skill-engine text.
- No JSON/system/instructional prompt fragments in preview.
- Mutual lock groups must support members from same and different teams.

## Current Runtime Touchpoints (inventory)

### LLM request lifecycle
- `app/services/role_pipeline.py`
  - `execute_role_request(...)`
    - resolves team-role and model
    - sends to LLM via `llm_executor.send_with_retries(...)`
    - runs skill loop and pre/post processors
  - `send_role_response(...)`
    - sends final answer to Telegram user/group
  - `run_chain(...)`
    - fan-out/orchestrator flow that calls execute/send for each role

### Skill loop lifecycle
- `app/services/skill_calling_loop.py`
  - `SkillCallingLoop.run(...)`
  - iterative LLM calls and skill execution inside one role request

### LLM retry semantics
- `app/llm_executor.py`
  - `send_with_retries(...)` retries in-process before raising

### Entry points that trigger role pipeline
- `app/handlers/messages_group.py`
  - `handle_group_buffered(...)` / `_flush_buffered(...)`
- `app/handlers/messages_private.py`
  - `handle_private_message(...)`

### Admin UI touchpoints for role list/cards
- `app/handlers/commands.py`
  - `/groups`, `/roles`
- `app/handlers/callbacks.py`
  - role cards, list rendering, callbacks for team-role operations

### Persistence and migration base
- `app/storage.py`
  - SQLite schema init + additive migrations
  - `team_roles` with `team_role_id`

## High-Risk Areas for Regression
1. `run_chain` orchestrator fan-out: status must not leak across delegated hops.
2. Private pending/token flows: failures should not leave stale busy state.
3. Skill-loop retries and parse fallbacks: keep busy while still in auto processing.
4. Send-to-user failures in `send_role_response`: must release to free.
5. Admin callback rendering performance when status/preview is added.

## Safety-Net for Next Stages
- Keep Stage 1 additive-only schema migration; no destructive DB changes.
- Introduce status service behind storage API boundary (no direct handler SQL).
- Add transactional acquire/release path before wiring UI.
- Add stale-lease cleanup guard before enabling lock-group enforcement in runtime.
- Keep current role execution behavior unchanged until Stage 4 integration point.

## Stage 0 Validation Commands (baseline)
- `python3 -m unittest tests.test_core_team_roles_use_cases`
- `python3 -m unittest tests.test_ltc12_hot_reload_full_scenario`
- `python3 -m unittest tests.test_interface_runtime_runner`

## Stage 0 Exit Criteria
- Runtime/UI/storage status touchpoints inventoried.
- Safety-net constraints documented.
- No runtime behavior changes introduced.
