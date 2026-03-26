# LTC-17 Manual Validation Checklist

## Goal
Confirm Telegram behavior after startup switch to interface runner.

## Preconditions
- Bot started with `interface.active=telegram`.
- No interface startup errors in logs.

## Checklist
- [ ] Bot starts through interface runner (log contains interface runtime startup line).
- [ ] `/groups` works in private owner chat.
- [ ] `/roles` works in private owner chat.
- [ ] Key callback flows open and execute (group card, role card, toggles).
- [ ] Group routing by role mention works.
- [ ] Replies in group and private contexts are returned as expected.
- [ ] Pending auth/token flow resumes role execution.
- [ ] Pending user-field flow resumes role execution.
- [ ] Session reset flow works (callback and `/role_reset_session`).
- [ ] No startup/dispatch exceptions in logs during smoke.

## Exit Criteria
- All checklist items are passed.
- No blocking runtime regressions observed.
