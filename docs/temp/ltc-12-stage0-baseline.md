# LTC-12 Stage 0 Baseline and Safety-Net

## Goal
Prepare safe implementation path for moving master-role source of truth from DB to per-role JSON files.

## Confirmed Requirements
- Master-role data fully moves from DB to JSON.
- DB keeps only team bindings/overrides and runtime data.
- Roles are loaded only on process startup (no hot-reload in this task).
- First startup on legacy DB performs automatic export from DB roles to JSON.
- On `role_name` conflict, existing JSON has priority; DB record is skipped and conflict is logged.

## Current State Snapshot
- Master-role source currently lives in DB table `roles`.
- Team/runtime already rely on `team_roles` + `team_role_id` and related tables:
  - `team_roles`
  - `user_role_sessions`
  - `role_prepost_processing`
  - `role_skills_enabled`
- `provider_user_data` currently role-scope keys are tied to `role_id`.

## High-Risk Touchpoints for LTC-12
- `app/storage.py`:
  - master-role CRUD (`upsert_role`, `get_role_by_*`, `list_active_roles`) currently DB-backed.
  - many APIs still resolve effective role through `role_id`.
- Runtime/handlers:
  - `/roles` and `/groups` UI paths currently query master roles via storage DB methods.
  - pipeline/session/auth/model resolution still consumes DB `Role` objects.
- LLM/user-field scope:
  - role-scoped provider values still keyed by numeric `role_id`.

## Safety-Net Added in Stage 0
- Schema capability helper methods in `Storage`:
  - `has_team_role_name_binding()`
  - `has_provider_user_data_role_name()`
  - `has_legacy_roles_table()`

These helpers allow additive migrations and runtime branching during transition phases.

## Stage 0 Exit Criteria
- Baseline inventory documented.
- Safety-net helper methods in place.
- No runtime behavior changes introduced.
