---
title: 80.3 Iteration Plans (MCP/Skills)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6324225
  parent_doc_path: 80-backlog-and-roadmap/_index.md
  local_id: 80-3-iteration-plans-mcp-skills
  parent_local_id: 80-backlog-and-roadmap
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 80.3 Iteration Plans (MCP/Skills)

## Objective
Define forward development stages for the LTC Skills and MCP ecosystem while preserving runtime safety, observability, and maintainability.

## Planning Principles
- keep transport/runtime separation intact,
- ship bounded capabilities first,
- enforce structured contracts and validation,
- expand power only after observability and safety controls are stable.

## Skills Roadmap

### Stage S1: Baseline Reliability
Focus:
- robust schema validation,
- deterministic error envelopes,
- loop guard stability.

Deliverables:
- strengthened validation coverage,
- improved diagnostics for parse and guard exits.

### Stage S2: Capability Growth
Focus:
- extend useful read-only skill families,
- refine per-role configuration handling.

Deliverables:
- additional bounded skills,
- role-level capability presets.

### Stage S3: Safety for Mutating Skills
Focus:
- controlled introduction of mutating operations,
- stricter policy and audit trails.

Deliverables:
- safety guardrails and policy docs,
- stronger runtime checks for high-impact calls.

## MCP Tooling Roadmap

### Stage M1: CLI and Local Reliability
Focus:
- predictable MCP runner behavior,
- better local diagnostics and error reporting.

### Stage M2: Publish Pipeline Hardening
Focus:
- stable repo-to-Confluence sync,
- improved drift/conflict visibility,
- stronger pre-publish validation.

### Stage M3: Operational Integration
Focus:
- CI-friendly publish checks,
- documented operational playbooks for publish failures.

## Cross-Cutting Milestones
- unified observability conventions across skills and tools,
- clear capability governance and approval policy,
- compatibility guarantees for skill and tool contracts.

## Exit Criteria for Each Stage
- explicit contract documentation updated,
- regression and smoke checks updated,
- operational risk controls validated,
- relevant sections in `40.*`, `50.*`, and `60.*` synchronized.
