---
title: 20.5 Security Threat Model
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5242914
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-5-security-threat-model
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.5 Security Threat Model

## Security Objectives
- Restrict bot execution to intended principal.
- Protect provider credentials and sensitive runtime fields.
- Limit unintended capability use by model output.
- Preserve operational integrity of group interactions.

## Trust Boundaries
- Telegram update stream (external input boundary).
- LLM provider APIs (external execution boundary).
- Tool/skill execution environment (capability boundary).
- Local SQLite and file system (data boundary).

## Primary Threats

### Unauthorized Invocation
Risk: non-owner users trigger processing in group chats.
Control: owner-only gating using configured owner identity.

### Prompt/Instruction Abuse
Risk: malicious content attempts to bypass intended role behavior.
Control: role-scoped prompts, explicit routing rules, optional mention requirements.

### Credential Exposure
Risk: provider tokens or user fields leak to group messages or logs.
Control: private collection flows, encrypted token storage, scoped retrieval.

### Over-privileged Skill Usage
Risk: model invokes tools/skills outside intended scope.
Control: per-role skill enablement, runtime limits, explicit skill contracts.

### Unsafe Tool Execution
Risk: shell/tool misuse when command capabilities are enabled.
Control: gated enable flags, safe-command policy, optional password challenge.

### Data Leakage Across Contexts
Risk: session or role state leaks across groups or roles.
Control: session keys include user, group, and role dimensions.

## Residual Risk Areas
- External provider behavior and availability.
- Misconfiguration of enabled capabilities.
- Human error in role prompt design.

## Recommended Hardening Practices
- Keep least-privilege skill policies per role.
- Rotate provider credentials on schedule.
- Review role configuration and tool access regularly.
- Monitor run logs for abnormal patterns.
