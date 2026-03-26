# LTC-18 Rollout/Rollback Runbook

## Scope
Final rollout for unified runtime role status (`FREE/BUSY`) and lock-group mutual blocking.

## Preconditions
- DB backup created (`bot.sqlite3` snapshot).
- App code for LTC-18 deployed.
- `roles_catalog` is valid.

## Rollout Steps
1. Stop bot process.
2. Start bot process (additive migration auto-applies on startup).
3. Run targeted tests:
   - `python3 -m unittest tests.test_ltc18_additive_migration tests.test_ltc18_storage_status_api tests.test_ltc18_runtime_status_service tests.test_ltc18_pipeline_busy_semantics -v`
4. Verify owner UI:
   - `/groups` role list has runtime `FREE/BUSY` marks.
   - Role card shows preview for busy roles.
   - `Lock Groups` section supports create/add/remove.
5. Execute manual smoke checklist (`docs/temp/ltc-18-manual-validation-checklist.md`).

## Rollback
1. Stop bot process.
2. Restore DB from snapshot.
3. Restore previous app release.
4. Start bot process.

## Notes
- Rollback to old code on new DB schema is not guaranteed; DB snapshot rollback is the expected path.
