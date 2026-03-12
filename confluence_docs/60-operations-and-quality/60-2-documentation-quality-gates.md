---
title: 60.2 Documentation Quality Gates
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6127617
  parent_doc_path: 60-operations-and-quality/_index.md
  local_id: 60-2-documentation-quality-gates
  parent_local_id: 60-operations-and-quality
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 60.2 Documentation Quality Gates

## Purpose
Quality gates keep LTC documentation publishable, consistent, and useful for both humans and AI agents.

## Gate 1: Metadata Validity
Each page must have valid front matter with required fields:
- `title`
- `confluence.space_id`
- `sync.mode`

Recommended checks:
- `confluence.space_id` matches target space,
- parent linkage is resolvable,
- no malformed YAML.

## Gate 2: Structural Consistency
- Numbered title format should match section hierarchy.
- Parent `_index.md` nodes should exist where expected.
- One page should represent one topic.

## Gate 3: Technical Accuracy
- Statements must reflect current LTC runtime behavior.
- File paths, commands, and config keys must be valid.
- References to skills/providers/tools must match implemented contracts.

## Gate 4: Operational Clarity
Pages must include actionable guidance where relevant:
- troubleshooting steps,
- verification commands,
- expected outputs or outcomes.

## Gate 5: Security and Scope Hygiene
- Do not include secrets or environment-specific sensitive values.
- Keep examples generic and safe.
- Avoid describing unsupported capabilities as available.

## Gate 6: Publish Readiness
Before sync to Confluence:
- markdown renders without broken sections,
- links resolve or are intentionally relative,
- changed pages are reviewed for drift against codebase.

## Suggested Enforcement
- Pre-merge review checklist for docs changes.
- Optional CI checks for YAML/front matter integrity.
- Periodic manual review for architecture and operations sections.
