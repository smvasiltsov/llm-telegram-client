---
title: 30.3 User Fields and Auth Modes
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5734401
  parent_doc_path: 30-llm-integration/_index.md
  local_id: 30-3-user-fields-and-auth-modes
  parent_local_id: 30-llm-integration
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 30.3 User Fields and Auth Modes

## User Fields in LTC
Providers can declare required runtime fields in `user_fields`.
Each field defines:
- `prompt`: text shown to the user,
- `scope`: `provider` or `role`.

LTC requests missing fields through private chat before continuing blocked execution paths.

## Scope Semantics
- `provider` scope: one value shared for provider usage.
- `role` scope: value is bound to a specific role context.

This allows fine-grained control over credentials and operational parameters.

## Runtime Resolution
During template rendering:
1. Router checks for `[[[field_key]]]` placeholders.
2. Storage lookup is performed using provider id and scope.
3. If value is missing, `MissingUserField` flow is triggered.
4. Bot requests value in private chat and stores it.

## Auth Modes
Provider config includes `auth.mode`.
Current runtime mainly distinguishes:
- `none`: no token requirement,
- non-`none`: treated as authentication-required flow in role checks.

Authentication behavior is enforced through provider field collection and runtime resolution rules.

## Storage and Safety Considerations
- Field values are persisted in `provider_user_data`.
- Sensitive values are never intended for group output.
- Token-like secrets are handled via project security services and encrypted token storage where applicable.

## Operational Practices
- Keep user field prompts explicit and unambiguous.
- Prefer role-scoped fields for least-privilege setups.
- Rotate sensitive values based on environment policy.
