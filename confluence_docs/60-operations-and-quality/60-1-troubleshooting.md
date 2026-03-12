---
title: 60.1 Troubleshooting
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6094849
  parent_doc_path: 60-operations-and-quality/_index.md
  local_id: 60-1-troubleshooting
  parent_local_id: 60-operations-and-quality
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 60.1 Troubleshooting

## Scope
This page covers common operational failures in LTC and practical diagnosis paths.

## Bot Does Not Respond in Group
### Checks
- Confirm the bot is still a member of the target group.
- Confirm the message sender is the configured `owner_user_id`.
- Confirm role mention syntax matches active role naming.
- Confirm routing policy (`require_bot_mention`) is satisfied.

### Diagnostics
- Inspect runtime logs for incoming group updates.
- Validate role exists and is enabled for the group.
- Verify selected model/provider is valid.

## Required User Field Is Not Accepted
### Checks
- Ensure the response is sent in private chat with the bot.
- Ensure the bot is currently waiting for that specific field.
- Verify input is plain value and not an unintended command.

### Diagnostics
- Confirm pending user-field state exists.
- Check provider field scope (`provider` vs `role`).

## Provider Not Found or Model Not Available
### Checks
- Confirm provider JSON exists in `llm_providers/`.
- Confirm provider `id` is unique and valid JSON parses.
- Confirm selected model id exists in provider `models` list.

### Diagnostics
- Restart bot and inspect provider-load logs.
- Validate role model reference format (`provider:model`).

## 401/403 or Authentication Errors
### Checks
- Confirm provider requires credentials.
- Confirm required user fields/tokens are present.
- Confirm endpoint headers/body templates include expected auth values.

### Diagnostics
- Inspect request contract mapping in provider config.
- Re-enter token or provider field values if needed.

## Skill Loop and Tool Failures
### Skill failures
- Check whether skill is enabled for current role.
- Check argument schema validity.
- Check skill runtime error envelope in logs/storage.

### Tool failures
- Confirm caller is owner.
- Confirm tool and bash subsystem are enabled.
- Confirm command is allowed by safe command policy.

## Escalation Path
1. Reproduce with minimal input.
2. Capture runtime log window.
3. Inspect related SQLite records (`skill_runs`, `tool_runs`, session/messages).
4. Apply config fix and re-test.
