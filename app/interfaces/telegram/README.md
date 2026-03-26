# Telegram Interface Module

This folder is the standalone Telegram transport module for interface runtime.

## Entry Point
- `adapter.py`
- factory: `create_adapter(core_port, runtime, config)`

## Adapter ID
- `telegram`

## Required Config
- `telegram_bot_token`
- `owner_user_id` (optional fallback to runtime value)

## Lifecycle
- `start()` initializes Telegram application and starts polling.
- `stop()` stops polling and shuts down application.

## Notes
- This module is loaded by `InterfaceRuntimeRunner` when:
  - `interface.active = "telegram"`
  - `interface.modules_dir = "app.interfaces"`
