---
title: 40.1 Skills Architecture
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5832705
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-1-skills-architecture
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.1 Skills Architecture

## Architectural Intent
LTC separates three runtime concepts:
- pre/post processing around LLM calls,
- model-callable skills,
- orchestrator loop that coordinates model and skills.

This separation is reflected in code, storage, and role configuration UI.

## Core Layers

### Skill Registry Layer
Responsibilities:
- discover and register skills,
- expose skill metadata for prompts,
- provide input schema for runtime validation,
- resolve `skill_id -> executor`.

Primary components:
- `app/skills/registry.py`
- `app/skills/contract.py`

### Orchestrator Layer
Responsibilities:
- build assistant payload with skills catalog,
- parse assistant decisions,
- execute skill calls and feed results back,
- enforce loop guards.

Primary component:
- `app/services/skill_calling_loop.py`

### Skill Runtime Layer
Responsibilities:
- validate arguments against schema,
- apply role-level enablement and config,
- execute skill safely,
- normalize outputs and errors.

Primary components:
- `app/skills/service.py`
- runtime contracts from `skills_sdk`.

### Storage and Observability Layer
Responsibilities:
- persist role-skill bindings,
- persist step-level execution logs,
- support diagnostics and audits.

Primary tables:
- `role_skills_enabled`
- `skill_runs`

## Role-Scoped Enablement Model
A skill is callable only if it is enabled for the active `(group_id, role_id)` pair.
The assistant receives only enabled skills in `skills.available`.

## Safety Model
Skills are declared with explicit mode and schema boundaries.
LTC uses bounded outputs and structured error envelopes to keep chat flow stable even when skill execution fails.

## First Built-in Capability Family
The current built-in family is filesystem-oriented (`fs.*`) with controlled execution scope and explicit config.
