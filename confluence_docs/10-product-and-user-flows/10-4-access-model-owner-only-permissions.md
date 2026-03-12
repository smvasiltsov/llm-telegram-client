---
title: 10.4 Access Model (Owner-only, Permissions)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5537793
  parent_doc_path: 10-product-and-user-flows/_index.md
  local_id: 10-4-access-model-owner-only-permissions
  parent_local_id: 10-product-and-user-flows
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 10.4 Access Model (Owner-only, Permissions)

## Ownership Model
LTC uses a single-owner operating model.
The configured `owner_user_id` is the only user whose group messages are processed by the bot.

## Permission Principles
- One bot instance is bound to one owner.
- Non-owner group participants are ignored by processing logic.
- Administrative configuration is performed through private chat with the bot.

This model reduces ambiguity and keeps control centralized.

## Group-Level Implications
Even when the bot is present in a multi-user group:
- only owner-originated requests trigger AI execution,
- role configuration is effectively controlled by the owner account,
- conversation context remains tied to owner/group/role scope.

## Provider and Field Access
Some providers require user-supplied fields (for example API tokens). These values are collected interactively via private flow and stored for runtime use.

Security-relevant expectations:
- fields are requested only when needed,
- values are scoped to runtime entities and not exposed in public group replies,
- operational handling follows project storage and encryption configuration.

## Skills and Capability Boundaries
Skills are enabled per role and act as explicit capability grants.
A role without a skill cannot invoke it through model `skill_call` responses.

Recommended control practice:
- enable only required skills,
- review role capabilities regularly,
- keep sensitive operations behind narrow role definitions.

## Operational Risk Controls
To keep access predictable:
- require explicit role mention in groups,
- keep private UI as the configuration channel,
- use session reset when role context becomes unreliable,
- track skill usage through runtime logs for auditability.
