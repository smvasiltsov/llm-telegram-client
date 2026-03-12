---
title: 30.4 Session/History Behavior
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5767169
  parent_doc_path: 30-llm-integration/_index.md
  local_id: 30-4-session-history-behavior
  parent_local_id: 30-llm-integration
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 30.4 Session/History Behavior

## Session Identity
LTC tracks conversation sessions by `(telegram_user_id, group_id, role_id)`.
This keeps conversational context isolated across roles and groups.

## Session Lifecycle
- Session is created or resolved before LLM execution.
- Each request appends user and assistant messages to `conversation_messages`.
- Session reset clears effective context for that role scope.

## Provider-Level History Switch
Provider config controls whether history is sent back to the external API:
- `history.enabled = true`: previously stored messages are included in outbound payload.
- `history.enabled = false`: only current request content is sent.

When enabled, `history.max_messages` limits the number of previous messages sent.

## Internal vs Outbound History
Important distinction:
- Internal storage of conversation messages is always maintained.
- Outbound history transmission depends on provider config.

This allows auditability and future reconfiguration without losing local message records.

## Send Path Behavior
At send time:
1. Router reads provider history settings.
2. If enabled, it fetches message history from storage.
3. It builds `messages` payload from stored role/content pairs.
4. It renders request template and performs provider call.
5. It stores both user input and assistant output.

## Practical Impact
- History-enabled providers support richer continuity.
- History-disabled providers reduce request payload size.
- Role/session isolation reduces cross-context contamination risk.
