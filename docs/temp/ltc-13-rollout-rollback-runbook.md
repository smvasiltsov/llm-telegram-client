# LTC-13 Rollout/Rollback Runbook

## Scope
Final rollout for `master role + team_role_id` architecture with additive auto-migration.

## Preconditions
- Build with LTC-13 stages 0-6 is prepared.
- DB backup/snapshot procedure is available.
- Short maintenance window is approved (if needed).

## Rollout Steps
1. Stop bot process.
2. Create DB backup snapshot.
3. Run migration smoke on a DB copy:
   - `python3 scripts/db_migration_smoke.py --db bot.sqlite3 --expect-table teams --expect-table team_bindings --expect-table team_roles --expect-table user_role_sessions --expect-table role_prepost_processing --expect-table role_skills_enabled --expect-column team_roles:team_role_id --expect-column user_role_sessions:team_role_id --expect-column role_prepost_processing:team_role_id --expect-column role_skills_enabled:team_role_id`
4. Start bot with target build.
5. Run readiness check:
   - `python3 scripts/team_rollout_readiness.py --config config.json`
6. Verify readiness output:
   - `ok=true`
   - no `missing_tables` and no `missing_columns`
   - no legacy tables/columns
   - no `*_without_team_id` counters
   - no `*_without_team_role_id` counters
7. Execute manual smoke checklist (`docs/temp/ltc-13-manual-validation-checklist.md`).

## Rollback Policy
Rollback to old code on migrated DB is not required for LTC-13.

## Rollback Steps (backup-based)
1. Stop bot process.
2. Restore DB from backup snapshot.
3. Deploy previous stable build.
4. Start bot and verify baseline health (`/groups`, `/roles`, one role invocation).

## Incident Notes
- If readiness fails, stop rollout and inspect readiness JSON.
- If runtime errors appear after deploy, restore backup and revert build.
