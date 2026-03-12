---
title: 60.3 Documentation Regression Checklist
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5931028
  parent_doc_path: 60-operations-and-quality/_index.md
  local_id: 60-3-documentation-regression-checklist
  parent_local_id: 60-operations-and-quality
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 60.3 Documentation Regression Checklist

## Usage
Run this checklist before publishing documentation updates to Confluence.

## A. Core Integrity
- [ ] All changed docs files parse as valid markdown.
- [ ] Front matter exists and is valid YAML.
- [ ] Required front matter fields are present.
- [ ] Section numbering and titles remain consistent.

## B. LTC Runtime Accuracy
- [ ] Commands are executable in current project layout.
- [ ] Paths and module names reflect current codebase.
- [ ] Config keys match `config.example.json` and runtime usage.
- [ ] Role, provider, skill, and tool behavior descriptions are current.

## C. Cross-Section Consistency
- [ ] No conflicting statements across 00-90 sections.
- [ ] Terminology matches glossary definitions.
- [ ] Architecture and operations guidance are aligned.

## D. Safety and Compliance
- [ ] No credentials, tokens, or private IDs in content.
- [ ] Security controls are described consistently.
- [ ] No unsupported feature claims.

## E. Publish Compatibility
- [ ] Parent-child hierarchy is valid for publish DAG.
- [ ] Confluence metadata (`space_id`, optional parent ids) is correct.
- [ ] Changed pages are ready for idempotent publish.

## F. Functional Spot Check
- [ ] One private configuration flow verified (`/groups`).
- [ ] One group role invocation verified (`@role`).
- [ ] Relevant skill/tool examples still match runtime behavior.
