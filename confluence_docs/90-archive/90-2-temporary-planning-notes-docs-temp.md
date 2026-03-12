---
title: 90.2 Temporary Planning Notes (docs/temp)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6389761
  parent_doc_path: 90-archive/_index.md
  local_id: 90-2-temporary-planning-notes-docs-temp
  parent_local_id: 90-archive
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 90.2 Temporary Planning Notes (docs/temp)

## Scope
This page records the purpose of temporary planning notes stored under `docs/temp` in LTC.

## Archived Source Set
Current temporary planning files:
- `docs/temp/orchestrator-engine-plan.md`
- `docs/temp/orchestrator-json-schema.md`
- `docs/temp/orchestrator-plan.md`
- `docs/temp/step7-regression-report.md`
- `docs/temp/README.md`

## Nature of These Notes
These files are working artifacts such as:
- exploratory plans,
- draft schemas,
- interim reports.

They may include assumptions that are no longer active in current runtime behavior.

## Documentation Policy for `docs/temp`
- retain for historical context,
- treat as non-authoritative for current implementation,
- migrate stable conclusions into primary sections (00-80),
- keep archive references so historical decisions remain discoverable.

## When to Reference
Use this archive page when:
- investigating origin of old design choices,
- tracing rationale from earlier drafts,
- validating whether an old note has already been formalized elsewhere.

## Replacement Priority
For active technical guidance, prefer:
- architecture pages (`20.*`),
- LLM integration pages (`30.*`),
- skills/MCP pages (`40.*`),
- development and operations pages (`50.*`, `60.*`),
- ADR pages (`70.*`).
