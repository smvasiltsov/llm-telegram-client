---
title: 00.3 Glossary
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5406721
  parent_doc_path: 00-start-here/_index.md
  local_id: 00-3-glossary
  parent_local_id: 00-start-here
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 00.3 Glossary

## Terms

### LTC
LLM-Telegram-Client project. A Telegram bot system that routes messages to LLMs with role-based behavior.

### Owner User
The Telegram user configured as `owner_user_id`. The bot processes group requests only from this user.

### Group Role
A role configuration bound to a specific Telegram group, including prompts, instructions, and model selection.

### Provider
A file-defined integration with an LLM backend, configured through `llm_providers/*.json`.

### Model
A concrete LLM model selectable within a provider configuration.

### User Fields
Per-user values required by some providers (for example, tokens or workspace paths), collected through private chat flow.

### Session
Conversation state associated with user, group, and role context.

### Runtime Context
Central dependency container used by handlers and services during bot execution.

### Prompt Builder
Service that assembles the final LLM prompt from role settings, message context, and instruction blocks.

### Pre/Post Processing
Server-side stages applied before and after LLM calls for transformation, filtering, or augmentation.

### Skill
Model-callable capability exposed to the assistant through the `skill_call` protocol.

### Skill Calling Loop
Execution loop where the LLM can request a skill, consume its result, and continue until producing a final answer.

### Plugin
Optional processing component that can modify output behavior or add post-response handling.

### MCP Tool Runner
CLI/runtime mechanism used to execute registered MCP tools with structured input.

### Skills Runner
CLI/runtime mechanism for invoking model-callable skills locally for testing and integration workflows.

### ADR
Architecture Decision Record. A documented technical decision with rationale and consequences.
