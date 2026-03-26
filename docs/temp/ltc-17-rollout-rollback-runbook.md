# LTC-17 Rollout/Rollback Runbook

## Scope
Final rollout for interface runtime architecture:
- core/interface contract,
- single active interface loader/runner,
- Telegram adapter in `app/interfaces/telegram`,
- external interface SDK artifacts.

## Preconditions
- Build with LTC-17 stages 0-8 is prepared.
- DB backup/snapshot procedure is available.
- `config.json` contains `interface` block with:
  - `active`,
  - `modules_dir`,
  - `runtime_mode=single`.

## Rollout Steps
1. Stop bot process.
2. Create DB backup snapshot.
3. Validate config for active interface:
   - check `interface.active=telegram`,
   - check `interface.modules_dir=app.interfaces`,
   - check `interface.runtime_mode=single`.
4. Run SDK smoke check for template contract:
   - `python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me`
5. Start bot with target build.
6. Verify startup logs:
   - `Starting interface runtime mode=single active=telegram modules_dir=app.interfaces`
   - no `InterfaceLoadError` / `InterfaceContractError`.
7. Execute manual smoke checklist (`docs/temp/ltc-17-manual-validation-checklist.md`).

## Rollback Policy
Rollback is backup-based and build-based.

## Rollback Steps
1. Stop bot process.
2. Restore DB snapshot.
3. Deploy previous stable build.
4. Start bot and verify baseline health (`/groups`, `/roles`, one group role invocation).

## Incident Notes
- If startup fails at interface loading, validate `interface.active` and module path.
- If runtime routing fails after start, switch back to previous build and restore backup.
