---
title: 10.2 Group/Role Management
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5472257
  parent_doc_path: 10-product-and-user-flows/_index.md
  local_id: 10-2-group-role-management
  parent_local_id: 10-product-and-user-flows
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 10.2 Group/Role Management

## Group as the Scope Boundary
LTC organizes configuration around Telegram groups. Roles are attached to groups, and each group can have its own role set.

## Role Lifecycle
Typical role lifecycle in a group:
1. Create role.
2. Provide role name and description.
3. Optionally provide system prompt.
4. Select model.
5. Configure optional instructions and runtime capabilities.

After creation, role settings can be updated at any time from the role card.

## Role Configuration Surface
A role may include:
- system prompt,
- general instructions applied to each message,
- reply-context instructions,
- model/provider selection,
- enabled skills,
- enabled pre/post processors.

These settings shape how requests are interpreted and executed.

## Session Behavior Per Role
Conversation context is isolated by user, group, and role key. This prevents accidental context leakage between roles or groups.

Operationally this means:
- changing role in the same group starts a different context,
- the same role name in another group can have separate behavior,
- role-level reset clears that role session without deleting the role.

## Deletion and Reset Operations
Role management supports:
- **reset session**: keep role settings, clear conversation context,
- **delete role**: remove role binding from the group.

These actions are intentionally explicit to reduce accidental data loss.

## Practical Management Guidelines
- Keep role purpose narrow and explicit.
- Prefer small, focused roles over one large generic role.
- Use clear role names that map to business intent.
- Review enabled skills periodically to keep least-privilege behavior.
