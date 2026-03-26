---
title: 20.7 LTC-12 Role JSON Catalog and Runtime Behavior
confluence:
  page_id: 7962625
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-7-ltc-12-role-json-catalog-and-runtime-behavior
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.7 LTC-12 Role JSON Catalog and Runtime Behavior

## Identity Source
Role identity is resolved only from JSON file basename (without `.json`).

Rules:
- valid basename regex: `^[a-z0-9_]+$`,
- no auto-normalization,
- internal `role_name` is metadata only.

## Catalog Load Rules
- files are read from `roles_catalog/*.json`,
- scan order is deterministic (sorted),
- duplicate by case-fold is resolved by first discovered file,
- non-winning duplicates are reported as catalog errors.

## Hot-Reload Contract
Catalog is refreshed on:
- `/roles` list requests,
- `/roles` callbacks (`mroles`, `mrole*`),
- runtime role resolution paths used in group/private flows.

This guarantees file changes are reflected without service restart.

## Error Model
Invalid files do not block valid role usage.

Common error categories:
- `invalid_file_name`,
- `invalid_json`,
- `duplicate_role_name_casefold`,
- `role_name_mismatch`.

## Runtime Resolution
Master defaults (`base_system_prompt`, `extra_instruction`, `llm_model`) come from JSON role catalog.

Team-level overrides remain higher priority and are merged on top.

## Binding Cleanup on File Remove/Rename
On catalog refresh, if active team binding role name is absent in the loaded catalog:
- binding is deactivated,
- auto-rebind to renamed file identity is not performed.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_role_catalog \
  tests.test_ltc12_role_catalog_service \
  tests.test_ltc12_hot_reload_full_scenario \
  tests.test_ltc12_manual_json_bind_runtime
```

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Hot-reload by filesystem watcher; current design is request-driven refresh.
