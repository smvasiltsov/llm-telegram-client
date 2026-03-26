---
title: 20.10 LTC-14 Team Abstraction over Telegram Group Domain
confluence:
  page_id: 8323087
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-10-ltc-14-team-abstraction
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.10 LTC-14 Team Abstraction over Telegram Group Domain

## Scope
LTC-14 replaces `group` as primary domain entity with `team`.

- `team` is canonical business scope.
- Telegram chat/group is transport mapping stored in `team_bindings`.
- UX command `/groups` remains as compatibility alias.

## Runtime and Data Effects
- Role routing is resolved by `team_id`.
- Sessions (`user_role_sessions`) are team-scoped via team-role binding.
- Pending/auth flows use team identity as primary scope.
- Skills and pre/post toggles remain team-role scoped.

## Database Entities
- `teams`
- `team_bindings`
- `team_roles`

Legacy `group` semantics are removed from primary runtime paths.

## Readiness and Validation Commands
```bash
python3 scripts/team_rollout_readiness.py --config config.json
```

```bash
python3 -m unittest \
  tests.test_storage_team_compat \
  tests.test_pending_store_team_dual_read \
  tests.test_team_migration_cleanup
```

## Operational Notes
- A short maintenance window is allowed for final cleanup migration.
- Rollback is expected via DB snapshot/backup, not by reverting to legacy runtime paths.

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Multi-interface runtime (`runtime_mode=multi`).
- Full removal of all Telegram UX aliases.
