---
title: 20.4 Data Model and Storage (SQLite entities)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5636097
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-4-data-model-and-storage-sqlite-entities
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.4 Data Model and Storage (SQLite entities)

## Storage Engine
LTC uses SQLite as the default persistence backend. Schema initialization and compatible migrations are handled in `app/storage.py`.

## Core Entities

### Team and Bindings
- `teams`: canonical team entity.
- `team_bindings`: interface links (Telegram chat and future interfaces).

### Role Layering (LTC-12)
- master-role source of truth: JSON files in `roles_catalog/`.
- role identity: file basename only.
- `team_roles`: binding of role identity to team with overrides and runtime flags.

Important columns:
- `team_roles.role_name`: file-based identity snapshot used for routing and cleanup logic.
- `team_roles.team_role_id`: surrogate binding id for session/capability tables.

### Runtime Data
- `user_role_sessions`: sessions scoped by `(telegram_user_id, team_id, team_role_id)`.
- `conversation_messages`: persisted conversation messages.
- `provider_user_data`: provider fields, including role-scoped values.

### Capability Bindings
- `role_prepost_processing`: pre/post processor bindings per team role.
- `role_skills_enabled`: skill bindings per team role.

### Observability
- `skill_runs`, `tool_runs`, `plugin_texts`.

## Modeling Notes
- Team-level overrides are stored in DB.
- Master role defaults (prompt/instruction/model) are loaded from JSON catalog and merged at runtime.
- Catalog refresh deactivates stale team role bindings when file identity disappears (remove/rename).
- Historical observability tables are not deeply normalized in current scope.

## Validation Commands
```bash
python3 scripts/db_migration_smoke.py \
  --db-path bot.sqlite3 \
  --expect-table teams \
  --expect-table team_bindings \
  --expect-table team_roles \
  --expect-column team_roles:team_role_id \
  --expect-column user_role_sessions:team_role_id
```

```bash
python3 -m unittest \
  tests.test_storage_team_compat \
  tests.test_ltc13_storage_team_role_api \
  tests.test_team_migration_cleanup
```

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Historical-log schema backfill (`tool_runs`, `skill_runs`, `conversation_messages`) beyond compatibility guarantees.
