---
title: 50.2 Codebase Structure and Layering
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5996565
  parent_doc_path: 50-development/_index.md
  local_id: 50-2-codebase-structure-and-layering
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.2 Codebase Structure and Layering

## Layering Principles
LTC follows a clear separation between transport handlers, reusable services, capability runtimes, and persistence.

## Main Areas

### Entry and Runtime Wiring
- `bot.py`: startup and lifecycle entrypoint.
- `app/app_factory.py`: application assembly and handler registration.
- `app/runtime.py`: shared `RuntimeContext` container.

### Transport Layer
- `app/handlers/*`: Telegram-facing handlers for commands, callbacks, group/private messages, and membership events.

### Service Layer
- `app/services/*`: business logic independent from Telegram transport details.
Key examples:
- prompt building,
- formatting,
- skill calling loop,
- plugin pipeline,
- tool execution.

### Capability Layers
- `app/skills/*`: model-callable skills registry/service runtime.
- `app/prepost_processing/*`: automatic pre/post hooks around LLM execution.
- `app/tools/*`: tool registry/adapters/execution.

### Persistence Layer
- `app/storage.py`: schema management and data operations.
- `app/models.py`: dataclasses representing domain records.

### Extension and Configuration Assets
- `llm_providers/*.json`: provider definitions.
- `plugins/*`: pluggable post-processing modules.
- `skills/*`: skill packages.

## Why This Structure Works
- Handlers remain thin and testable.
- Runtime behavior is explicit through centralized context.
- Extensions can evolve without rewriting transport core.
- Storage and observability remain consistent across subsystems.
