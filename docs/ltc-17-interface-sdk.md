# LTC-17: Interface SDK and Core Contract

## Goal
Decouple transport interface from core runtime so new interfaces can be added as modules without core code changes.

## Active Interface Configuration
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

- `active`: interface id (module name).
- `modules_dir`: python package root where adapters live.
- `runtime_mode`: currently only `single`.

## Runtime Contract
Core contract is defined in:
- `app/core/contracts/interface_io.py`
- `interfaces_sdk/contract.py` (external SDK mirror)

Inbound:
- `InboundEvent`
  - `event_id`, `interface_id`, `channel_id`, `actor_id`
  - `event_type`: `message|command|callback|membership|system`
  - `text`, `payload`, `reply_to_event_id`, `timestamp`

Outbound:
- `OutboundAction`
  - `action_id`, `action_type`, `target_channel_id`, `target_actor_id`
  - `text`, `structured_payload`, `correlation_event_id`
  - `action_type`: `send_message|edit_message|ack|request_input|show_menu`

Adapter lifecycle:
- `interface_id: str`
- `async start()`
- `async stop()`
- factory function: `create_adapter(core_port, runtime, config)`

## Runtime Loader and Startup
Runtime is started through:
- `bot.py` -> `InterfaceRuntimeRunner`
- `app/interfaces/runtime/*` (descriptor + loader + runner)

Startup uses config:
- `interface.active`
- `interface.modules_dir`
- `interface.runtime_mode`

Current supported mode:
- `runtime_mode=single`

## Module Layout
Interface module path is resolved as:
- `<modules_dir>.<active>.adapter`

Example for Telegram:
- `app/interfaces/telegram/adapter.py`
- `app/interfaces/telegram/README.md`
- `app/interfaces/telegram/module_manifest.json`

## SDK for External Developers
Files:
- `interfaces_sdk/contract.py` — portable contract types/protocols.
- `interfaces_sdk/template_adapter.py` — minimal adapter template.
- `interfaces_sdk/validator.py` — adapter contract validation.
- `scripts/interface_sdk_smoke.py` — CLI smoke validation.
- `interface_module_kit/` — self-contained agent-first kit (contract, templates, examples, emulator, validator, FAQ).

Validation command:
```bash
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
```

Expected output: `OK`.

Kit smoke command:
```bash
python3 -m interface_module_kit.validator.smoke_runner --scenario all
```

Expected output:
- `"ok": true`
- per-scenario `receive_ok=true`, `send_ok=true`.

## Run Commands
- Start bot with active Telegram interface:
  - `python3 bot.py`
- Validate runtime tests:
  - `python3 -m unittest tests.test_interface_runtime_registry tests.test_interface_runtime_loader tests.test_interface_runtime_runner tests.test_telegram_adapter_contract`

## Error Model
Runtime loader errors:
- `InterfaceConfigError` — invalid runtime mode or missing adapter config.
- `InterfaceLoadError` — module import failure.
- `InterfaceContractError` — adapter violates required interface.

## Known Issues
- In broader regression suite there is non-blocking legacy failure:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`
- Running Telegram adapter requires `python-telegram-bot` package in environment.

## Out of Scope
- Only one active interface at a time (`runtime_mode=single`).
- Telegram handlers still operate as transport implementation details inside `app/interfaces/telegram`.
- Core port processing is scaffolded and will be expanded in next stages.
