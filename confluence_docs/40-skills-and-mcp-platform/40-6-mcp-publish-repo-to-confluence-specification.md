---
title: 40.6 MCP Publish (Repo -> Confluence) Specification
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5963777
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-6-mcp-publish-repo-to-confluence-specification
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.6 MCP Publish (Repo -> Confluence) Specification

## Goal
MCP Publish synchronizes repository documentation to Confluence with deterministic, incremental behavior.
Repository docs are treated as source of truth.

## Repository Model
Primary structure:
- `confluence_docs/` as docs root,
- `_meta.yaml` for global publish settings,
- markdown files with YAML front matter,
- `.confluence-publish/state.json` for local publish state.

Directory hierarchy maps to Confluence page hierarchy.

## Front Matter Contract
Each page includes metadata such as:
- `title`,
- `confluence.space_id`,
- optional `confluence.page_id`,
- optional `confluence.parent_page_id`,
- `sync.mode` and sync policy fields.

If `page_id` is absent, publish flow can create the page and persist returned id.

## Parent Resolution Strategy
Parent page is resolved by precedence:
1. explicit `confluence.parent_page_id`,
2. parent folder `_index.md` page id,
3. global `root_page_id` from `_meta.yaml`.

## Publish Algorithm Summary
1. Scan docs tree and parse front matter.
2. Validate metadata and build parent-first DAG.
3. Convert markdown to Confluence storage format.
4. Compute content hash and compare with local state.
5. Skip unchanged pages when changed-only mode is active.
6. Create/update Confluence pages as needed.
7. Update local state records.

## Conflict and Drift Handling
Default synchronization policy is repo-first.
Safe mode can fail or skip when remote drift is detected.
Version conflicts are handled with controlled retry behavior.

## CLI and MCP Interface
The spec defines both:
- local CLI execution modes (dry-run/apply/changed-only),
- MCP contract with structured input/output for orchestration.

## Operational Guidance
- Keep file names human-readable.
- Store Confluence ids in front matter, not in file names.
- Prefer one-way sync (repo to Confluence).
- If reverse sync is needed, handle it as separate controlled tooling.
