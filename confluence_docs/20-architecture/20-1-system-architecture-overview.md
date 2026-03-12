---
title: 20.1 System Architecture Overview
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5242895
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-1-system-architecture-overview
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.1 System Architecture Overview

## Purpose
LTC is a role-driven Telegram bot platform that routes user requests from Telegram chats to LLM providers, optionally enriches the interaction with model-callable skills, and returns formatted responses back to Telegram.

## Architectural Layers

### Transport Layer
`app/handlers/*` processes Telegram updates and user interactions:
- command handling,
- callback handling,
- group message handling,
- private message handling,
- membership events.

### Orchestration and Business Services
`app/services/*` contains reusable application logic:
- prompt building,
- formatting and safe output rendering,
- plugin integration,
- skill-calling loop,
- tool execution.

### LLM Integration Layer
LLM connectivity is driven by provider definitions from `llm_providers/*.json` and runtime components for routing and execution.

### Capability Layer
Two independent extension systems are available:
- model-callable skills (`app/skills/*`),
- pre/post processing hooks (`app/prepost_processing/*`).

### Persistence Layer
`app/storage.py` and `app/models.py` manage SQLite persistence for users, groups, roles, sessions, messages, and runtime metadata.

## Runtime Container
`RuntimeContext` is the dependency container shared across handlers via `context.application.bot_data["runtime"]`. It provides access to storage, routers, executors, registries, buffers, and policy flags.

## Main Data Path
1. User message is received in Telegram.
2. Handler resolves scope (group/private), role, and context.
3. Prompt is assembled and provider/model are selected.
4. Optional pre-processing executes.
5. LLM request runs directly or through skill loop.
6. Optional post-processing executes.
7. Formatted result is sent to Telegram.

## Architectural Characteristics
- Role and group scoping for behavior isolation.
- File-based provider extensibility.
- Explicit capability control through per-role enablement.
- Deterministic persistence model in SQLite.
- Clear separation between transport code and domain services.
