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
LTC is a role-driven LLM bot platform with pluggable interfaces. Telegram is the active default interface, but runtime startup and contracts are interface-agnostic.

## Architectural Layers

### Interface Runtime Layer (LTC-17)
- `app/interfaces/runtime/*`: interface descriptor, loader, and runtime runner.
- `bot.py`: starts runtime through `InterfaceRuntimeRunner` using `config.interface.active`.
- `app/interfaces/<interface_id>/adapter.py`: concrete transport adapter (Telegram currently).

### Transport Adapter Layer
`app/interfaces/telegram/*` and `app/handlers/*` process Telegram updates:
- command and callback handling,
- team chat and private chat message handling,
- membership events.

### Core Use-Case Layer
`app/core/use_cases/*` contains transport-agnostic role/team operations invoked by adapters.

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
`app/storage.py` and `app/models.py` manage SQLite persistence for teams, bindings, team-role records, sessions, messages, and runtime metadata.

### Master Role Catalog (LTC-12)
- JSON files in `roles_catalog/*.json` are the source of truth for master-role defaults.
- Role identity is resolved from file basename only.
- Catalog is hot-reloaded on `/roles` flows and runtime role resolution.

## Runtime Container
`RuntimeContext` is the dependency container shared across handlers via `context.application.bot_data["runtime"]`. It provides access to storage, routers, executors, registries, buffers, and policy flags.

## Main Data Path
1. Interface adapter receives user event and converts it to core event shape.
2. Runtime resolves team and team-role scope.
3. Master defaults are loaded from role JSON catalog and merged with team overrides.
4. Prompt is assembled and provider/model are selected.
5. Optional pre-processing executes.
6. LLM request runs directly or through skill loop.
7. Optional post-processing executes.
8. Formatted result is converted to adapter actions and sent via active interface.

## Team and Role Model (LTC-13/LTC-14)
- `team` is canonical domain entity.
- `team_bindings` map interface channels to teams.
- Role behavior is layered:
  - master role (JSON),
  - team role binding (`team_role_id`) with team-level overrides.

## Runtime Configuration
`config.json`:
```json
{
  "interface": {
    "active": "telegram",
    "modules_dir": "app.interfaces",
    "runtime_mode": "single"
  }
}
```

## Validation Commands
```bash
python3 -m unittest \
  tests.test_interface_runtime_registry \
  tests.test_interface_runtime_loader \
  tests.test_interface_runtime_runner \
  tests.test_telegram_adapter_contract
```

```bash
python3 -m unittest \
  tests.test_ltc12_hot_reload_full_scenario \
  tests.test_ltc13_inheritance_override \
  tests.test_storage_team_compat
```

## Known Issues
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Multi-interface runtime mode (`runtime_mode=multi`).
