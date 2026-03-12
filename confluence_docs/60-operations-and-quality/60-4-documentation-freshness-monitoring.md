---
title: 60.4 Documentation Freshness Monitoring
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6160385
  parent_doc_path: 60-operations-and-quality/_index.md
  local_id: 60-4-documentation-freshness-monitoring
  parent_local_id: 60-operations-and-quality
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 60.4 Documentation Freshness Monitoring

## Objective
Keep LTC documentation aligned with code and runtime behavior over time.

## Freshness Signals
Track changes that commonly cause documentation drift:
- updates in handler/service/runtime modules,
- provider contract changes in `llm_providers/`,
- skill/tool contract updates,
- config schema changes in `config.example.json`,
- storage schema changes in `app/storage.py`.

## Monitoring Model
Use two complementary modes:
- **Change-triggered review**: docs review when relevant code/config areas change.
- **Periodic review**: scheduled check of high-risk sections (architecture, operations, integration).

## High-Risk Sections
Prioritize frequent validation for:
- `20.* Architecture`
- `30.* LLM Integration`
- `40.* Skills & MCP Platform`
- `50.* Development`
- `60.* Operations & Quality`

## Practical Mechanisms
- Tag docs-impacting PRs with required docs review.
- Maintain per-page `last_reviewed` metadata when needed.
- Use dry-run publish reconciliation to detect metadata mismatches.

## Drift Response Workflow
1. Identify stale page.
2. Link stale statements to current code/config source.
3. Update page content and metadata.
4. Re-run regression checklist.
5. Publish synchronized changes.

## Outcome Metrics
Suggested monitoring metrics:
- number of stale pages detected per period,
- mean time to refresh stale docs,
- number of publish-time metadata conflicts,
- number of broken links/front matter errors.
