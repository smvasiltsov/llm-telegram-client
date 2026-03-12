---
title: 50.4 Local Validation and Smoke Tests
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5439527
  parent_doc_path: 50-development/_index.md
  local_id: 50-4-local-validation-and-smoke-tests
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.4 Local Validation and Smoke Tests

## Static Validation
Run syntax compilation checks:
```bash
python3 -m py_compile \
  bot.py app/*.py app/handlers/*.py app/services/*.py \
  app/tools/*.py app/skills/*.py app/prepost_processing/*.py plugins/*.py
```

## Unit and Integration Baseline
Run tests:
```bash
python3 -m unittest discover -s tests -v
```

## Targeted Runtime Smoke Tests
Perform minimal end-to-end checks after changes:
- `/groups` navigation in private chat,
- role card sections `Skills` and `Pre/Post Processing`,
- group request using role mention (`@role`),
- optional `/bash` flow when tools are enabled.

## Provider Change Validation
After provider updates:
- ensure provider loads at startup,
- assign provider model to role,
- send sample request and verify answer,
- verify user-field prompts if required.

## Skill Change Validation
After skill updates:
- list/execute skill through `scripts/skills_runner.py`,
- verify role enablement behavior in UI,
- verify structured `skill_call` loop behavior on sample prompt.

## Tool Change Validation
After tool updates:
- list/exec via `scripts/mcp_tool_runner.py`,
- verify owner-only access behavior,
- verify command restrictions and output limits.
