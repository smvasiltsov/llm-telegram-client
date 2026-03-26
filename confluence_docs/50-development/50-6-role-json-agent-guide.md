---
title: 50.6 Role JSON Authoring Guide for AI Agents
confluence:
  page_id: 8028161
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 50-development/_index.md
  local_id: 50-6-role-json-agent-guide
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.6 Role JSON Authoring Guide for AI Agents

## File Contract
- path: `roles_catalog/<role_name>.json`
- identity: basename only
- valid basename: `^[a-z0-9_]+$`

## Field Contract
Required:
- `base_system_prompt` (aliases: `system_prompt`, `prompt`)

Optional:
- `description` (`summary`)
- `extra_instruction` (`instruction`)
- `llm_model` (`model`)
- `is_active` (`active`, `enabled`)
- `schema_version` (if present, must equal `1`)
- `role_name` (metadata only)

Identity contract:
- `role_name = <file basename>` only.
- JSON `role_name` is ignored for identity and used only as metadata.

## Canonical Example
```json
{
  "schema_version": 1,
  "role_name": "analyst",
  "description": "Analyzes risks and trade-offs",
  "base_system_prompt": "You are an analyst.",
  "extra_instruction": "Use concise structured bullets.",
  "llm_model": null,
  "is_active": true
}
```

## Validation and Error Handling
Errors are reported without blocking valid files:
- invalid basename,
- malformed JSON,
- duplicate by case-fold,
- mismatch between payload `role_name` and basename.

Duplicate rule:
- file list is deterministically sorted,
- first file wins by case-fold key,
- later duplicates are reported in errors.

## Operational Expectations
- `/roles` reflects file changes on each request (hot-reload),
- valid roles are listed together with catalog errors,
- deleting/renaming a file deactivates old team bindings.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_role_catalog \
  tests.test_ltc12_role_catalog_service \
  tests.test_ltc12_hot_reload_full_scenario \
  tests.test_ltc12_manual_json_bind_runtime
```

## Out of Scope
- Filesystem watcher-based hot-reload (refresh is request-triggered).
