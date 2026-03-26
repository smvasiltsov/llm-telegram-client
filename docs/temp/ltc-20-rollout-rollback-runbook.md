# LTC-20 Rollout/Rollback Runbook

## Scope
Global delay before switching role runtime status from `BUSY` to `FREE`.

## Preconditions
- DB backup created (`bot.sqlite3` snapshot).
- App code with LTC-20 + startup hotfix deployed.
- `config.json` contains `runtime_status.free_transition_delay_sec` (default `0`).

## Rollout Steps
1. Stop bot process.
2. Deploy code.
3. Set target value for `runtime_status.free_transition_delay_sec`.
4. Start bot process (idempotent schema migration auto-runs).
5. Run targeted checks:
   - `python3 -m unittest tests.test_ltc18_additive_migration tests.test_ltc18_storage_status_api tests.test_ltc18_runtime_status_service tests.test_ltc18_pipeline_busy_semantics -v`
6. Execute manual smoke checklist:
   - `docs/temp/ltc-20-manual-validation-checklist.md`

## Rollback
1. Stop bot process.
2. Restore DB snapshot.
3. Restore previous app release.
4. Start bot process.

## Notes
- Startup hotfix: delayed-release index is created only when column exists (safe for legacy DBs).
- Rollback to old code on newer DB shape is not guaranteed; snapshot rollback is primary path.
