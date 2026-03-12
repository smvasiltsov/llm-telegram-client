---
title: 20.4 Data Model and Storage (SQLite entities)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5636097
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-4-data-model-and-storage-sqlite-entities
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.4 Data Model and Storage (SQLite entities)

## Storage Engine
LTC uses SQLite as the default persistence backend. Schema initialization and backward-compatible migrations are handled by `Storage` in `app/storage.py`.

## Primary Domain Entities

### Users and Authorization
- `users`: Telegram user identity, authorization flag, creation timestamp.
- `auth_tokens`: encrypted provider token storage and auth state metadata.

### Group and Role Configuration
- `groups`: known Telegram groups and active status.
- `roles`: reusable role definitions (name, description, base prompts, default model).
- `group_roles`: role binding to group with per-group overrides and enablement flags.

### Session and Conversation Data
- `user_role_sessions`: session mapping by `(telegram_user_id, group_id, role_id)` with lifecycle timestamps.
- `conversation_messages`: persisted message history by session id.

### Provider/User Runtime Data
- `provider_user_data`: provider-scoped key/value fields with optional role scope.

### Capability Bindings
- `role_prepost_processing`: enabled pre/post processors per `(group, role)` with optional config JSON.
- `role_skills_enabled`: enabled skills per `(group, role)` with optional config JSON.

### Observability and Execution Logs
- `skill_runs`: skill execution chain, step metadata, duration, status, serialized input/output.
- `tool_runs`: command/tool execution metadata and status.
- `plugin_texts`: plugin-managed text storage.

## Modeling Principles
- Composite keys enforce scope boundaries.
- Runtime features are enabled explicitly per role-group pair.
- JSON fields allow flexible per-feature configuration.
- Timestamp fields support auditability and operational diagnostics.
