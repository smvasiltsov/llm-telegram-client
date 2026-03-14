# LTC-13 Stage 0 Baseline and Safety-Net

## Goal
Prepare safe implementation path for `master role + team_role_id` migration without UX regressions.

## Current Baseline (observed)
- `roles` exists as global master-role table:
  - `role_id, role_name, description, base_system_prompt, extra_instruction, llm_model, is_active`
- `team_roles` exists, but without surrogate id:
  - current key is `(team_id, role_id)`
  - no `team_role_id`
- runtime and handlers are team-first (`team_id`), with UX aliases preserved (`/groups`, callbacks).
- session/skills/prepost are already team-scoped by `(team_id, role_id)` and do not yet have `team_role_id`.

## High-Risk Touchpoints for LTC-13
- `app/storage.py`: central schema/migrations and all role/session/skills/prepost CRUD.
- `app/services/role_pipeline.py`, `app/services/skill_calling_loop.py`: role execution path.
- `app/handlers/callbacks.py`, `app/handlers/messages_private.py`, `app/handlers/commands.py`: UI compatibility and payload parsing.
- `app/session_resolver.py`, `app/auth.py`: warm-up and session lifecycle.

## Safety-Net Added in Stage 0
1. `scripts/db_migration_smoke.py`:
- added `--forbid-table` and `--forbid-column` checks,
- output now includes `unexpected_tables`, `unexpected_columns`.

2. `app/storage.py`:
- added schema capability guards:
  - `has_team_role_surrogate_id()`
  - `has_session_team_role_id()`
  - `has_prepost_team_role_id()`
  - `has_skill_team_role_id()`

These guards are non-breaking and intended for additive migration stages.

## Suggested Smoke Commands for Next Stages
- additive stage:
  - `python3 scripts/db_migration_smoke.py --db-path bot.sqlite3 --expect-table team_roles --expect-column team_roles:team_role_id --expect-column user_role_sessions:team_role_id --expect-column role_prepost_processing:team_role_id --expect-column role_skills_enabled:team_role_id`
- cleanup stage:
  - `python3 scripts/db_migration_smoke.py --db-path bot.sqlite3 --forbid-column user_role_sessions:role_id --forbid-column role_prepost_processing:role_id --forbid-column role_skills_enabled:role_id`

## Backward Compatibility Constraint (unchanged)
- `/groups`, `/roles`, callback payload format and user scenarios must remain behaviorally unchanged for users.
