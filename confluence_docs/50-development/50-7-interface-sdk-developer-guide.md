---
title: 50.7 Interface SDK Developer Guide (LTC-17)
confluence:
  page_id: 8028180
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 50-development/_index.md
  local_id: 50-7-interface-sdk-developer-guide
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.7 Interface SDK Developer Guide (LTC-17)

## Goal
Build new transport interfaces outside core logic and plug them into LTC via config.

## SDK Artifacts
- `interfaces_sdk/contract.py`
- `interfaces_sdk/template_adapter.py`
- `interfaces_sdk/validator.py`
- `scripts/interface_sdk_smoke.py`
- `interface_module_kit/` (self-contained external dev kit)

## Adapter Requirements
1. Place module at `app/interfaces/<interface_id>/adapter.py`.
2. Export `create_adapter(core_port, runtime, config)`.
3. Adapter must provide:
- `interface_id == <interface_id>`
- `async start()`
- `async stop()`

## Development Flow
1. Copy `interfaces_sdk/template_adapter.py`.
2. Implement transport client and map incoming updates to `core_port.handle_event(...)`.
3. Implement graceful shutdown in `stop()`.
4. Validate contract:

```bash
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
```

5. Enable in config:

```json
{
  "interface": {
    "active": "<interface_id>",
    "modules_dir": "app.interfaces",
    "runtime_mode": "single"
  }
}
```

6. Start runtime:
```bash
python3 bot.py
```

7. Run runtime tests:
```bash
python3 -m unittest \
  tests.test_interface_runtime_registry \
  tests.test_interface_runtime_loader \
  tests.test_interface_runtime_runner \
  tests.test_telegram_adapter_contract
```

## Failure Diagnostics
- `import_error:*` — module path or dependency issue.
- `missing_factory:create_adapter` — wrong adapter entrypoint.
- `factory_error:*` — runtime/config assumptions inside factory.
- `missing_method:start|stop` — lifecycle contract violation.
- `interface_id_mismatch:*` — adapter ID differs from configured ID.

## Known Issues
- Telegram adapter runtime requires `python-telegram-bot` package in environment.
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Multi-interface concurrent runtime (`runtime_mode=multi`).
