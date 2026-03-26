---
title: 20.8 Interface Runtime and Core Contracts (LTC-17)
confluence:
  page_id: 7897096
  parent_page_id: 98699
  space_id: 5144580
  parent_doc_path: 20-architecture/_index.md
  local_id: 20-8-interface-runtime-and-contracts
  parent_local_id: 20-architecture
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 20.8 Interface Runtime and Core Contracts (LTC-17)

## Purpose
Define a stable interface between core runtime and transport adapters so UI/transport implementations can be developed independently.

## Runtime Selection
`config.json`:

```json
{
  "interface": {
    "active": "telegram",
    "modules_dir": "app.interfaces",
    "runtime_mode": "single"
  }
}
```

Loader resolves module as:
- `<modules_dir>.<active>.adapter`
- startup path: `bot.py` -> `InterfaceRuntimeRunner`.

## Contract Types
Core contract:
- `app/core/contracts/interface_io.py`

External SDK mirror:
- `interfaces_sdk/contract.py`

Input envelope:
- `InboundEvent`
  - identity (`event_id`, `interface_id`)
  - routing (`channel_id`, `actor_id`, `event_type`)
  - content (`text`, `payload`, `reply_to_event_id`)

Output envelope:
- `OutboundAction`
  - identity (`action_id`, `correlation_event_id`)
  - target (`target_channel_id`, `target_actor_id`)
  - instruction (`action_type`, `text`, `structured_payload`)

## Adapter Lifecycle Contract
Required adapter fields/methods:
- `interface_id: str`
- `async start() -> None`
- `async stop() -> None`
- factory: `create_adapter(core_port, runtime, config)`

## Error Classes
- `InterfaceConfigError`
- `InterfaceLoadError`
- `InterfaceContractError`

These classes isolate startup/config failures from domain runtime.

## Current Runtime Scope
- `runtime_mode=single` only.
- Telegram implementation moved to `app/interfaces/telegram/adapter.py`.
- Startup in `bot.py` runs via `InterfaceRuntimeRunner`.

## SDK and Smoke
- `interfaces_sdk/*`: portable contract and adapter template.
- `interface_module_kit/*`: self-contained external developer kit (contract, templates, examples, emulator, validator, FAQ).

Validation commands:
```bash
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
python3 -m interface_module_kit.validator.smoke_runner --scenario all
```

## Runtime Validation Commands
```bash
python3 -m unittest \
  tests.test_interface_runtime_registry \
  tests.test_interface_runtime_loader \
  tests.test_interface_runtime_runner \
  tests.test_telegram_adapter_contract
```

## Known Issues
- Telegram adapter runtime requires `python-telegram-bot` package in environment.
- Non-blocking legacy regression in broader suite:
  `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- `runtime_mode=multi` and concurrent multi-adapter orchestration.
