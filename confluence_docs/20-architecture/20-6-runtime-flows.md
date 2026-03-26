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

## Flow A: Team-Scoped Role Request in Chat
1. Interface adapter receives a message event.
2. Runtime resolves channel -> `team_id` via `team_bindings`.
3. Runtime resolves role identity and `team_role_id`.
4. Catalog defaults are loaded from JSON and merged with team overrides.
5. Session resolver obtains or creates team-role session.
6. Prompt builder composes final LLM input.
7. Pre-processing stages execute.
8. LLM execution runs (direct or skill loop).
9. Post-processing stages execute.
10. Formatting service renders output and adapter sends response back to channel.

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

## Flow D: Master Role and Team Binding Configuration
1. User opens `/roles` in private chat.
2. Runtime refreshes `roles_catalog/*.json` on request.
3. Valid roles are listed together with catalog errors (if any).
4. User can bind master role to existing team.
5. User opens `/groups` to manage only bound team roles and team overrides.

## Flow E: Session Reset
1. User requests role session reset in private UI.
2. Runtime removes or refreshes session record for target role scope.
3. Subsequent role request starts with clean context.

## Flow F: File Remove/Rename Cleanup (LTC-12)
1. Catalog refresh detects missing role identity.
2. Active team-role bindings for missing identity are deactivated.
3. Removed/renamed role is not routed in runtime anymore.
4. No automatic rebinding to renamed file identity is performed.

## Runtime Reliability Notes
- Database-backed state enables deterministic recovery between restarts.
- Explicit team scoping reduces accidental cross-team behavior.
- Structured logs for skill/tool runs support troubleshooting and audits.

## Validation Commands
```bash
python3 -m unittest \
  tests.test_ltc12_hot_reload_full_scenario \
  tests.test_ltc12_manual_json_bind_runtime \
  tests.test_storage_team_compat \
  tests.test_pending_store_team_dual_read
```
