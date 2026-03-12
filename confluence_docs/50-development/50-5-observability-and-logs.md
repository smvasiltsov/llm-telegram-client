---
title: 50.5 Observability and Logs
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6029313
  parent_doc_path: 50-development/_index.md
  local_id: 50-5-observability-and-logs
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.5 Observability and Logs

## Primary Logging Channel
Runtime logs are emitted to the terminal process where `bot.py` is running.
This is the first-line source for operational debugging.

## What to Watch in Logs
- startup/config load status,
- provider discovery and model registry initialization,
- LLM send attempts and errors,
- skill-calling loop decisions,
- tool execution outcomes,
- plugin server lifecycle events.

## Structured Runtime Signals
LTC stores execution metadata in SQLite for deeper analysis:
- `skill_runs`: step-level skill calls, status, duration, output/error,
- `tool_runs`: tool command status and execution metadata,
- `conversation_messages`: persisted message history per session.

## Typical Debug Sequence
1. Reproduce issue with minimal request.
2. Inspect terminal logs around timestamp.
3. Check related SQLite rows (`skill_runs`, `tool_runs`, sessions/messages).
4. Validate role/provider configuration state.
5. Re-run with narrowed scope.

## Observability by Subsystem

### LLM Integration
Monitor provider id resolution, response errors, retries, timeout behavior.

### Skills
Monitor loop step count, repeated-call guard triggers, validation failures, and structured skill error envelopes.

### Tools
Monitor access control outcomes (`forbidden` vs allowed), command policy enforcement, stdout/stderr truncation metadata.

## Operational Recommendations
- Keep logs from startup and reproduction windows.
- Correlate chat context with runtime records using role/chat/user dimensions.
- Review error patterns before adjusting prompts or enabling additional capabilities.
