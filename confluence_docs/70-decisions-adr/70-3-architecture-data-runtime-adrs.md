---
title: 70.3 Architecture/Data/Runtime ADRs
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5734420
  parent_doc_path: 70-decisions-adr/_index.md
  local_id: 70-3-architecture-data-runtime-adrs
  parent_local_id: 70-decisions-adr
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 70.3 Architecture/Data/Runtime ADRs

## Purpose
This page summarizes accepted architectural and runtime decisions that shape LTC behavior.

## ADR-A1: Central Runtime Dependency Container
### Decision
Use `RuntimeContext` as the single in-memory dependency container shared across handlers.

### Rationale
- consistent access to runtime services,
- reduced implicit global coupling,
- easier wiring at startup.

### Impact
Handlers remain transport-focused, while services hold reusable domain logic.

## ADR-A2: Role and Group Scoped Configuration Model
### Decision
Bind behavior through `(group, role)` configuration overlays and keep role defaults separate.

### Rationale
- allows group-specific behavior with shared role concepts,
- avoids duplicated global role definitions.

### Impact
Storage includes `roles` and `group_roles` split; UI edits target scoped role settings.

## ADR-D1: Session Isolation by User/Group/Role
### Decision
Persist session keys by `(telegram_user_id, group_id, role_id)`.

### Rationale
- prevents context bleed across roles/groups,
- preserves predictable conversation continuity.

### Impact
Session reset can be applied surgically per role scope.

## ADR-D2: SQLite as Primary Operational Store
### Decision
Use SQLite for runtime state, configuration bindings, and observability logs.

### Rationale
- simple deployment model,
- deterministic local persistence,
- sufficient for current runtime scale.

### Impact
Schema includes conversation, capability bindings, and execution logs (`skill_runs`, `tool_runs`).

## ADR-R1: File-Driven Provider Contracts
### Decision
Define LLM providers via JSON contracts in `llm_providers/`.

### Rationale
- integration changes can be configuration-first,
- clearer provider portability across environments.

### Impact
Provider errors are often diagnosable from config without core code changes.

## ADR-R2: Explicit Skill Protocol and Guarded Loop
### Decision
Allow model-callable capabilities only via structured `skill_call` protocol in bounded loop.

### Rationale
- deterministic parser behavior,
- safer execution boundaries,
- auditable step-by-step interaction history.

### Impact
Runtime enforces schema validation, enabled-skill checks, and repeat/step limits.

## ADR-R3: Separation of Skills vs Pre/Post Processing
### Decision
Keep model-invoked skills and automatic pre/post processors as separate systems.

### Rationale
- avoids semantic confusion,
- enables independent governance and rollout.

### Impact
Distinct registries, UI sections, and storage bindings.

## Review Policy
When architectural behavior changes, update this page and corresponding detailed ADR entries to keep decisions traceable.
