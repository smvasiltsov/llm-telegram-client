---
title: 20.3 Message Processing Pipeline (group/private)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5603329
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-3-message-processing-pipeline-group-private
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.3 Message Processing Pipeline (group/private)

## Pipeline Overview
LTC handles private and group messages through separate handlers with shared service primitives. The split enforces clear UX boundaries: configuration in private chat, role-based execution in groups.

## Group Message Pipeline
1. Telegram update enters group message handler.
2. Request is validated against owner and routing policy.
3. Role mention is resolved.
4. Role/group settings are loaded.
5. Prompt is built from role prompt, optional instructions, and reply context.
6. Pre-processing hooks run.
7. LLM executes directly or through skill-calling loop.
8. Post-processing hooks run.
9. Response is formatted and sent back to group.

## Private Message Pipeline
1. Telegram update enters private message handler.
2. Handler checks pending operations (provider fields, role setup steps, auth steps).
3. If update maps to configuration flow, storage is updated.
4. For command or callback routes, corresponding role/group UI action executes.
5. Bot returns confirmation or next-step prompt.

## Shared Processing Rules
- Session context is keyed by user, group, and role.
- Provider-required fields may interrupt flow and request additional private input.
- Output formatting is centralized in formatting service.
- Skill and pre/post systems are optional and role-scoped.

## Failure Paths
Typical interruption points:
- missing role mention,
- unauthorized sender,
- unresolved provider/model,
- missing required user fields,
- provider timeout or external API failure.

Handlers surface user-facing errors while preserving internal runtime logs.
