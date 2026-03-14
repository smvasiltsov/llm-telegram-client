# LTC-14.2 Stage 1: Final Pure-Team Design and Legacy Inventory

## Scope and Goal
This stage defines the final target architecture after LTC-14: `team` is the only domain scope in runtime/storage, while Telegram remains only as transport and binding interface.

## Final Pure-Team Target Design

### 1) Domain model
- Canonical scope key: `(telegram_user_id, team_id, role_id)`.
- `team` is the only business aggregate for role configuration and routing.
- Telegram chat/group identity is not part of business keys and not a primary scope.

### 2) Telegram compatibility layer
- Keep UX command aliases (`/groups`, existing callback patterns) unchanged.
- Resolve target `team_id` through `team_bindings(interface_type='telegram', external_id=<chat_id>)`.
- `chat_id` remains only as transport delivery target (send/edit messages), not as config/scope primary key.

### 3) Storage model (target)
- Keep and use as primary:
  - `teams`
  - `team_bindings`
  - `team_roles`
- Convert to team-scoped:
  - sessions: `user_role_sessions` keyed by `(telegram_user_id, team_id, role_id)`
  - pre/post config: team-scoped key `(team_id, role_id, prepost_processing_id)`
  - skills config: team-scoped key `(team_id, role_id, skill_id)`
- Remove legacy domain tables from primary path:
  - `group_roles`
  - `groups` (if no longer needed for any migration/runtime path)

### 4) Runtime/handlers target
- All pipeline entry points operate with `team_id` only.
- `group_id`/`chat_id` may be present only as transport fields for Telegram send/reply.
- Remove dual-read/fallback branches and rollout-mode conditional branching once migration readiness is guaranteed.

## Legacy Inventory (Current Codebase)

### A) Runtime flags and rollout branches
- `app/config.py`: `team_rollout_mode`, `team_dual_read_enabled`, `team_dual_write_enabled`.
- `app/runtime.py`: same rollout flags in `RuntimeContext`.
- `bot.py`: rollout warning/logging for team mode + dual_read.
- `app/handlers/messages_private.py`: `_resolve_pending_team_id(..., fallback_team_id=...)` fallback path.

### B) Legacy mapping/storage API still active
- `app/storage.py`:
  - mapping helpers: `resolve_team_id_by_group_id_legacy`, `resolve_group_id_by_team_id_legacy`.
  - group wrappers still used by handlers: `ensure_group_role`, `get_group_role`, `list_group_roles`, `list_roles_for_group`, `get_group_role_name`, `get_role_for_group_by_name`, `group_role_name_exists`.
  - session legacy API remains (`get/save/touch_user_role_session` by `group_id`).
  - team->group fallback remains for sessions/skills/prepost (`resolve_group_id_by_team_id_legacy`).

### C) Handlers/services still group-first in interfaces
- `app/handlers/messages_group.py`: `upsert_group`, `seed_group_roles`, legacy team resolve by group.
- `app/handlers/membership.py`: `upsert_group`, `seed_group_roles`, `set_group_active`.
- `app/services/group_reconcile.py`: list/reconcile via `storage.list_groups()` and `group.group_id`.
- `app/handlers/commands.py` and `app/handlers/callbacks.py`: pervasive `group_id` contract in command args, callback payloads, and storage calls.

### D) DB legacy structures still present
- `groups` table (and `team_id` backfill column).
- `group_roles` table (kept in sync with `team_roles`, currently additive compatibility).
- `user_role_sessions.group_id` is still part of primary key and read/write paths.
- `role_prepost_processing` and `role_skills_enabled` still keyed by `group_id`.

### E) Tests and readiness tooling still encode additive phase
- Compatibility tests: `tests/test_storage_team_compat.py`, `tests/test_team_migration_additive.py`, `tests/test_pending_store_team_dual_read.py`.
- Readiness script: `scripts/team_rollout_readiness.py` still validates `groups` backfill as rollout criterion.

## Pure-Team Cleanup Boundary for Implementation

### Keep
- `/groups` command and existing Telegram UX text/callback prefixes as aliases.
- `team_bindings` with `interface_type='telegram'` as transport mapping layer.

### Remove
- All `*_legacy` storage resolvers and fallback logic.
- Dual-read/dual-write/runtime rollout flags and branches from runtime code.
- Group-primary storage methods/queries as primary code path.
- DB structures that encode group as domain key (`group_roles`, and `groups` if not required post-migration).

### Migrate in DB cleanup step
- Rebuild `user_role_sessions` to team-only PK.
- Rebuild pre/post and skills tables to team-keyed versions.
- Backfill from existing rows before dropping legacy tables/columns.

## Stage-1 Exit Criteria
- Final target design fixed (team-only domain, Telegram binding-only).
- Complete inventory of legacy code paths/tables/scripts prepared.
- Clear removal boundary defined (what stays as alias vs what is deleted).
- Stage 2 can proceed with code cleanup and cleanup migration implementation.
