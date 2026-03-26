---
title: 10.2 Group/Role Management
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5472257
  parent_doc_path: 10-product-and-user-flows/_index.md
  local_id: 10-2-group-role-management
  parent_local_id: 10-product-and-user-flows
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 10.2 Group/Role Management

## Team Scope and Master Roles
Role behavior is split into two layers:
- **master role** (file-based JSON in `roles_catalog`),
- **team role binding** (team-specific enablement and overrides).

Master-role identity is file-based and independent from team binding identity (`team_role_id`).

## Role Identity (LTC-12)
- identity is file basename only (`<name>.json`),
- valid basename regex: `^[a-z0-9_]+$`,
- payload `role_name` is metadata only.

## `/roles` User Flow
- list is loaded from disk on every request (hot-reload),
- valid roles are shown even when some files are invalid,
- catalog errors are shown in UI.

Typical catalog errors surfaced to users:
- invalid file name,
- malformed JSON,
- duplicate by case-fold,
- `role_name` mismatch between payload and file name.

## `/groups` User Flow
Within a team, users manage bound roles:
- add role from master-role list,
- adjust team-level overrides and capabilities,
- reset role session,
- remove binding from team.

Creating a brand-new role from team context is not the primary path; new master roles are created in `/roles`.

## Deletion/Rename Behavior
If a role file is removed or renamed:
- old team bindings for previous identity are deactivated automatically,
- no automatic transfer to new identity is performed.

## Session Behavior
Role context remains isolated by user + team + role binding.
Reset operation clears session state without deleting master role file.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_ltc13_storage_team_role_api \
  tests.test_ltc13_inheritance_override \
  tests.test_storage_team_compat \
  tests.test_pending_store_team_dual_read
```

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.
