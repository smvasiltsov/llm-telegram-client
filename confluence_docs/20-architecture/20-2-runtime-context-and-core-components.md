---
title: 20.2 Runtime Context and Core Components
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5406740
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-2-runtime-context-and-core-components
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.2 Runtime Context and Core Components

## RuntimeContext Role
`RuntimeContext` is the central in-memory container that wires core services and shared state for request processing. It is created during startup and passed to the interface runtime runner.

## Core Components

### Storage and Security
- `storage`: SQLite access abstraction.
- `cipher`: token encryption/decryption utility.
- `auth_service`: authorization checks and owner-scoped behavior.
- `team_service`: team and team-binding helpers.

### LLM Stack
- `llm_router`: resolves provider/model routing.
- `llm_executor`: executes provider calls.
- `session_resolver`: resolves and creates role sessions.
- `provider_registry`, `provider_models`, `provider_model_map`: loaded provider metadata.
- `role_catalog_service`: JSON catalog refresh, role identity resolve, stale binding cleanup.

### Message and Pending State
- `message_buffer`, `private_buffer`: buffered text handling.
- `pending_store`, `pending_user_fields`: pending user input tracking.
- `pending_prompts`, `pending_role_ops`: temporary UI operation state.

### Skills and Processing
- `skills_registry`, `skills_service`: skill metadata and runtime execution.
- `prepost_processing_registry`: pre/post hooks registry.
- `plugin_manager`, `plugin_server`: plugin coordination.

### Tools and Execution
- `tool_service`, `tool_mcp_adapter`: tool execution and MCP adapter integration.
- Bash policy fields: enable flag, safe commands, password, per-user working directory and pending auth state.

### Formatting and Delivery Policy
- `formatting_mode`, `allow_raw_html`: output rendering behavior.
- Skill loop policy flags (`skills_max_steps_per_request`, follow-up mode, usage prompt).
- `interface_runtime`: active adapter lifecycle state and dispatch helpers.

## Interface Runtime Components (LTC-17)
- `app/interfaces/runtime/registry.py`: validates runtime mode and module descriptors.
- `app/interfaces/runtime/loader.py`: imports `<modules_dir>.<active>.adapter`.
- `app/interfaces/runtime/runner.py`: starts and stops the active interface adapter.

## Contract Surfaces
Core-facing dataclasses/protocols:
- `app/core/contracts/interface_io.py`

External SDK mirror:
- `interfaces_sdk/contract.py`

## Why This Structure Matters
- Handlers/adapters remain thin and transport-focused.
- Services remain reusable and testable.
- Cross-cutting settings are centrally managed.
- Runtime behavior is predictable because dependencies are explicit.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_interface_runtime_registry \
  tests.test_interface_runtime_loader \
  tests.test_interface_runtime_runner \
  tests.test_core_team_roles_use_cases
```
