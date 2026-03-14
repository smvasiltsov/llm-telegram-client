# LTC-13 Manual Validation Checklist

## Goal
Validate `master role + team_role_id` behavior and backward-compatible Telegram UX.

## Preconditions
- Bot runs with migrated DB.
- `scripts/team_rollout_readiness.py` returns `ok=true`.

## Checklist
- [ ] `/groups` shows Telegram chats.
- [ ] `/roles <group_id>` shows expected role list.
- [ ] Create new role via UI flow (name + model selection).
- [ ] Clone existing role into another group and verify no duplicate master role created.
- [ ] In cloned role, verify inherited overrides: display name, prompt, model, suffix/reply-prefix.
- [ ] In cloned role, verify skills and pre/post bindings are copied.
- [ ] Toggle skill and pre/post processing callbacks still work.
- [ ] Mention route in group (`@role`) works.
- [ ] Pending auth/token flow still resumes execution.
- [ ] Reset session via callback and `/role_reset_session` still works.

## Exit Criteria
- All items passed without regressions in logs.
