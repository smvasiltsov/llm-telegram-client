# LTC-14.2 Pure Team Mode Manual Validation Checklist

## Goal
Confirm critical Telegram UX and runtime flows in pure team mode.

## Preconditions
- Bot is running with migrated DB.
- `scripts/team_rollout_readiness.py` returns `ok=true`.

## Checklist
- [ ] `/groups` in private chat shows available Telegram chats.
- [ ] Open group from `/groups` and see role list.
- [ ] Toggle role enable/disable via callback buttons.
- [ ] Set orchestrator mode and revert to normal.
- [ ] Update system prompt from UI; change persists.
- [ ] Update suffix/reply-prefix from UI; changes persist.
- [ ] Change model via callback; change persists.
- [ ] Reset role session from UI and via command (`/role_reset_session <group_id> <role>`).
- [ ] Group chat routing works for `@role` mention.
- [ ] Pending token flow works (auth requested in private, then response resumes in group).
- [ ] Pending user field flow works and resumes role execution.
- [ ] `/roles <group_id>` returns expected roles.

## Exit Criteria
- All items checked.
- No runtime exceptions in logs for storage/session/pending/auth flows.
