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
`RuntimeContext` is the central in-memory container that wires all core services and shared state for request processing. It is created during app startup and attached to Telegram application bot data.

## Core Components

### Storage and Security
- `storage`: SQLite access abstraction.
- `cipher`: token encryption/decryption utility.
- `auth_service`: authorization checks and owner-scoped behavior.

### LLM Stack
- `llm_router`: resolves provider/model routing.
- `llm_executor`: executes provider calls.
- `session_resolver`: resolves and creates role sessions.
- `provider_registry`, `provider_models`, `provider_model_map`: loaded provider metadata.

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

## Why This Structure Matters
- Handlers remain thin and transport-focused.
- Services remain reusable and testable.
- Cross-cutting settings are centrally managed.
- Runtime behavior is predictable because dependencies are explicit.
