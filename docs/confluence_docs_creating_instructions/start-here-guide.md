# Confluence Auto Sync Authoring Guide

## Purpose

This guide is for AI developers who prepare local documentation before publishing via `confluence_auto_sync`.

Goals:
- keep documentation structure locally in repository;
- define parent-child links without заранее известных Confluence IDs;
- let MCP write real `space_id/page_id/parent_page_id` after publish.

## Directory Structure

Use this layout:

```text
confluence_docs/
  _meta.yaml
  00-start/
    _index.md
    glossary.md
  architecture/
    _index.md
    runtime-flows.md
```

Rules:
- each folder is a section;
- `_index.md` is the parent page of a section;
- other markdown files are child pages.

## Front Matter Contract

Each markdown file must start with YAML front matter.

Minimal template:

```yaml
---
title: "Page Title"
confluence:
  local_id: "arch-runtime-flows"
  parent_local_id: "arch-index"
sync:
  mode: publish
---
```

Required:
- `title`
- `sync.mode` (`publish` only)

Optional local-link fields:
- `confluence.local_id`
- `confluence.parent_local_id`
- `confluence.parent_doc_path`

Real Confluence fields can be absent before first publish:
- `confluence.space_id`
- `confluence.page_id`
- `confluence.parent_page_id`

These are written by MCP after successful publish.

## How To Define Parent Links

Use one of these methods:

1. `parent_local_id` (recommended)

```yaml
confluence:
  local_id: "arch-runtime-flows"
  parent_local_id: "arch-index"
```

2. `parent_doc_path`

```yaml
confluence:
  local_id: "arch-runtime-flows"
  parent_doc_path: "architecture/_index.md"
```

3. Implicit folder structure
- if no explicit parent link is set, folder hierarchy is used;
- top-level anchor uses `root_page_id` from MCP call (or `_meta.yaml` fallback).

## local_id Rules

- `local_id` must be unique in `confluence_docs`;
- use stable slug-like IDs, e.g. `arch-index`, `qa-regression`;
- do not reuse one `local_id` for different files.

## MCP Publish Arguments

For `mcp_publish`, pass at least:
- `repo_path`
- `docs_root`
- `mode`
- `space_id` (required)

Recommended:
- `root_page_id` (target root anchor)
- `rewrite_frontmatter_ids=true`

Example:

```json
{
  "operation": "mcp_publish",
  "repo_path": "/path/to/repo",
  "docs_root": "confluence_docs",
  "space_id": "1081356",
  "root_page_id": "1114122",
  "mode": "apply",
  "rewrite_frontmatter_ids": true
}
```

## What MCP Writes Back

After successful publish, MCP updates front matter with real values:
- `confluence.space_id`
- `confluence.page_id`
- `confluence.parent_page_id`

This is the source of truth for future incremental updates.

## Recommended Workflow

1. Create folders and markdown files.
2. Fill `title`, `local_id`, `parent_local_id`/`parent_doc_path`, `sync.mode=publish`.
3. Run `dry-run` and inspect `created/updated/skipped/errors/warnings`.
4. Run `apply` with `space_id`, `root_page_id`, `rewrite_frontmatter_ids=true`.
5. Commit updated files with rewritten front matter IDs.

## Troubleshooting

- If pages are not moved under new root, ensure `root_page_id` is passed in MCP call.
- If parent link fails, check that `parent_local_id`/`parent_doc_path` target exists.
- If page belongs to different Confluence space, MCP can recreate page in target space and remap children within run.
