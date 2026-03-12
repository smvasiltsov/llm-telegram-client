---
title: 10.3 Typical User Scenarios
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5505025
  parent_doc_path: 10-product-and-user-flows/_index.md
  local_id: 10-3-typical-user-scenarios
  parent_local_id: 10-product-and-user-flows
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 10.3 Typical User Scenarios

## Scenario 1: Ask a Role in Group Chat
1. User opens a group where LTC is present.
2. User writes a request and mentions a role (for example, `@analyst`).
3. Bot resolves role configuration and model.
4. Bot returns response in the same conversation.

Use case: day-to-day analysis or drafting tasks in team chat.

## Scenario 2: Configure a New Role
1. User opens private chat with the bot.
2. User runs `/groups`.
3. User selects group and creates a new role.
4. User sets prompt/model and optional instructions.

Use case: creating specialized assistants for different team workflows.

## Scenario 3: Provider Requires User Fields
1. User invokes role in group.
2. Bot detects missing required provider field.
3. Bot asks for the value in private chat.
4. After value is saved, group requests continue normally.

Use case: per-user credentials or runtime parameters required by provider integration.

## Scenario 4: Enable Skills for a Role
1. User opens role card in private UI.
2. User enters Skills section.
3. User enables selected skills for that role.
4. Next requests can trigger `skill_call` loop as needed.

Use case: augmenting model responses with file operations or tool-assisted actions.

## Scenario 5: Troubleshoot Incorrect Behavior
1. User notices unstable or off-target responses.
2. User reviews role prompt/instructions/model.
3. User resets role session if context drift is suspected.
4. User validates behavior with a short test request.

Use case: restoring predictable output quality.

## Scenario 6: Maintain Safe Operations
1. User reviews active roles and enabled skills.
2. User disables unused capabilities.
3. User keeps only required configuration per group.

Use case: minimizing operational risk while preserving productivity.
