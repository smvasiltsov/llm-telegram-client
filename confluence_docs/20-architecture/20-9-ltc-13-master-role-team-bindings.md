---
title: 20.9 LTC-13 Master Role and Team Role Bindings
confluence:
  page_id: 8323106
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-9-ltc-13-master-role-team-bindings
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.9 LTC-13 Master Role and Team Role Bindings

## Scope
LTC-13 splits role behavior into:
- master role (global role definition),
- team role binding (team-specific binding with its own identity).

## Data Model
- Role identity source for master defaults is file-based (`roles_catalog/<role_name>.json`).
- Team binding table: `team_roles`.
- Each binding has surrogate key `team_role_id`.

This means `(team_id, role_name)` is not the only identity; runtime and related tables can reference `team_role_id`.

## Inheritance and Overrides
Master role provides defaults:
- base system prompt,
- extra instruction,
- default model/mode.

`team_roles` can override:
- `display_name`,
- prompt/instruction fields,
- model/mode flags,
- enablement and capability bindings.

## Runtime Behavior
- `/roles` manages master roles.
- `/groups` manages team role bindings.
- Removing role from team removes/deactivates binding only; master role stays available.
- Session, skills, and pre/post settings are scoped by team role binding.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_ltc13_storage_team_role_api \
  tests.test_ltc13_inheritance_override \
  tests.test_ltc13_additive_migration
```

```bash
python3 scripts/db_migration_smoke.py \
  --db-path bot.sqlite3 \
  --expect-table team_roles \
  --expect-column team_roles:team_role_id \
  --expect-column user_role_sessions:team_role_id \
  --expect-column role_prepost_processing:team_role_id \
  --expect-column role_skills_enabled:team_role_id
```

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Deep historical-log normalization.
- Removing UX compatibility aliases (`/groups`, old callback payload shapes).
