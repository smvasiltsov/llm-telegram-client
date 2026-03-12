---
title: 70.1 ADR Index
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5472276
  parent_doc_path: 70-decisions-adr/_index.md
  local_id: 70-1-adr-index
  parent_local_id: 70-decisions-adr
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 70.1 ADR Index

## Purpose
This index tracks architecture and runtime decisions for LTC in ADR format.

## ADR Status Legend
- **Accepted**: active and implemented.
- **Superseded**: replaced by a newer ADR.
- **Proposed**: under review and not yet enforced.

## Current ADR Entries

### ADR-002: Event-Driven Processing for Telegram Updates
- **Status**: Accepted
- **Area**: Runtime orchestration
- **Summary**: Process Telegram updates through a staged, event-driven handler pipeline with role-based routing and loop-based skill execution.
- **Reference**: `70.2 ADR-002 Event-Driven Processing for Telegram Updates`

### Runtime Context as Central Dependency Container
- **Status**: Accepted
- **Area**: Runtime composition
- **Summary**: Use `RuntimeContext` as the single dependency hub injected into handlers/services.
- **Reference**: `70.3 Architecture/Data/Runtime ADRs`

### Role+Group Scoped Session Isolation
- **Status**: Accepted
- **Area**: Conversation safety
- **Summary**: Scope sessions by user, group, and role to prevent cross-context leakage.
- **Reference**: `70.3 Architecture/Data/Runtime ADRs`

### File-Based Provider Contracts
- **Status**: Accepted
- **Area**: LLM integration
- **Summary**: Define providers via JSON contracts in `llm_providers/` to keep integration configuration-driven.
- **Reference**: `70.3 Architecture/Data/Runtime ADRs`

### Per-Role Capability Enablement for Skills
- **Status**: Accepted
- **Area**: Security and control
- **Summary**: Expose only enabled skills per role/group and enforce runtime validation for every call.
- **Reference**: `70.3 Architecture/Data/Runtime ADRs`

## ADR Maintenance Rules
- Every accepted architectural change should have an ADR entry.
- Superseded decisions should remain discoverable with replacement references.
- ADR titles should be stable and implementation-oriented.
