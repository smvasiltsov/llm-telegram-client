# LTC-14.2 Pure Team Mode Rollout/Rollback Runbook

## Scope
Runbook for final switch to pure team mode after cleanup migration.

## Preconditions
- Build with LTC-14.2 stages 1-4 changes deployed.
- Backup strategy available (DB snapshot/backup).
- Maintenance window approved.

## Rollout Steps
1. Stop bot process.
2. Create DB backup snapshot.
3. Run migration smoke on a DB copy:
   - `python3 scripts/db_migration_smoke.py --db-path bot.sqlite3 --expect-table teams --expect-table team_bindings --expect-table team_roles --expect-table user_role_sessions --expect-table role_prepost_processing --expect-table role_skills_enabled --expect-column user_role_sessions:team_id --expect-column role_prepost_processing:team_id --expect-column role_skills_enabled:team_id`
4. Start bot with target build.
5. Run readiness check:
   - `python3 scripts/team_rollout_readiness.py --config config.json`
6. Verify readiness output:
   - `ok=true`
   - no missing tables/columns
   - no legacy tables/columns present
   - no `*_without_team_id` counters
7. Execute manual smoke checklist (see companion checklist doc).

## Rollback Policy
Rollback to old code on migrated DB is not required.

## Rollback Steps (backup-based)
1. Stop bot process.
2. Restore DB from backup snapshot.
3. Deploy previous stable bot build.
4. Start bot and validate basic health (`/groups`, one group role invocation).

## Incident Notes
- If readiness fails: do not continue to smoke; collect output JSON and inspect failed checks.
- If smoke fails after successful readiness: stop rollout and restore from backup.
