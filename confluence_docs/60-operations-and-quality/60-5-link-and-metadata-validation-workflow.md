---
title: 60.5 Link and Metadata Validation Workflow
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6062100
  parent_doc_path: 60-operations-and-quality/_index.md
  local_id: 60-5-link-and-metadata-validation-workflow
  parent_local_id: 60-operations-and-quality
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 60.5 Link and Metadata Validation Workflow

## Goal
Validate documentation links and front matter metadata before repository-to-Confluence publish.

## Validation Scope
- internal markdown links,
- section anchors,
- front matter integrity,
- Confluence-specific metadata values.

## Step 1: Front Matter Validation
For each page:
- parse YAML front matter,
- ensure required fields exist,
- confirm `confluence.space_id` matches target publish space,
- validate optional `page_id` and `parent_page_id` are numeric when present.

## Step 2: Hierarchy Validation
- ensure parent resolution is deterministic,
- ensure parent nodes exist (`_index.md` or explicit parent id),
- ensure no circular parent dependencies.

## Step 3: Link Validation
- check local relative links resolve to existing docs paths,
- check anchors reference existing headings,
- flag links to archived pages when not intentional.

## Step 4: Publish-State Validation
- compare changed docs with `.confluence-publish/state.json`,
- verify unchanged pages are skippable by hash,
- flag pages with missing state but existing page ids for review.

## Step 5: Pre-Publish Gate Decision
- pass: allow publish apply run,
- warn: allow dry-run only until issues are reviewed,
- fail: block publish for invalid metadata/hierarchy.

## Error Handling Guidelines
- invalid YAML: hard fail,
- missing required metadata: hard fail,
- unresolved local links: fail unless explicitly allowed,
- unresolved optional external links: warning.

## Recommended Automation
- run validation in CI for docs-impacting changes,
- execute local validation before manual publish,
- store validation report artifacts for auditability.
