---
title: 20.6 Runtime Flows
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5341204
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-6-runtime-flows
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.6 Runtime Flows

## Flow A: Role-Based Group Request
1. Owner posts a group message with role mention.
2. Group handler resolves role and group-role configuration.
3. Session resolver obtains or creates role session.
4. Prompt builder composes final LLM input.
5. Pre-processing stages execute.
6. LLM execution runs (direct or skill loop).
7. Post-processing stages execute.
8. Formatting service renders output for Telegram.
9. Response is delivered to group.

## Flow B: Provider Field Resolution
1. Group or private action triggers model call.
2. Runtime detects missing required provider/user field.
3. Bot requests value in private chat.
4. User provides value.
5. Value is persisted in provider user data store.
6. Original interaction can continue with valid runtime context.

## Flow C: Skill-Calling Loop
1. LLM returns a `skill_call` payload.
2. Runtime validates skill id and arguments.
3. Skill service executes selected skill.
4. Output is recorded in `skill_runs`.
5. Skill result is passed back into next LLM step.
6. Loop ends when model returns final plain-text answer.

## Flow D: Role Configuration in Private UI
1. User opens `/groups` in private chat.
2. User selects group and role.
3. Role options are updated (prompt, model, skills, processors).
4. Changes are persisted in storage.
5. Next group invocation uses updated role behavior.

## Flow E: Session Reset
1. User requests role session reset in private UI.
2. Runtime removes or refreshes session record for target role scope.
3. Subsequent role request starts with clean context.

## Runtime Reliability Notes
- Database-backed state enables deterministic recovery between restarts.
- Explicit flow boundaries (group/private) reduce accidental cross-mode behavior.
- Structured logs for skill/tool runs support troubleshooting and audits.
