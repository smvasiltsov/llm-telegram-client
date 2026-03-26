# LTC-17 Stage 0: Safety-Net and Connectivity Inventory

## Goal
Capture the current Telegram coupling points before refactor to interface-agnostic core and adapter runtime.

## Telegram-Coupled Entry Points
- `bot.py`
  - Telegram app lifecycle, polling startup, command scope bootstrap.
- `app/app_factory.py`
  - Telegram ApplicationBuilder setup.
  - All `CommandHandler`, `CallbackQueryHandler`, `ChatMemberHandler`, `MessageHandler` registrations.

## Telegram Transport Layer (current)
- `app/handlers/commands.py`
  - `/groups`, `/roles`, `/tools`, `/bash`, role prompt/session commands.
- `app/handlers/callbacks.py`
  - Role/group UI callbacks, skills/prepost toggles, model updates, bind flows.
- `app/handlers/messages_group.py`
  - Group buffering + routing + pending auth save + run chain.
- `app/handlers/messages_private.py`
  - Pending state machine, auth/token, master-role create flow, pending replay.
- `app/handlers/membership.py`
  - Bot membership and group seen handling.
- `app/handlers/messages_common.py`
  - Shared transport helpers around token/user field prompts.

## Telegram Types Leaking into Non-Adapter Areas
- `app/services/role_pipeline.py`
  - Depends on `telegram.ext.ContextTypes` and `telegram.constants.ParseMode`.
  - Contains send/reply side effects and pending state coupling.
- `app/services/formatting.py`, `app/services/plugin_pipeline.py`, `app/services/group_reconcile.py`
  - Direct Telegram types/errors used in service-level code.

## Runtime Coupling Surface
- `RuntimeContext` is stored in `context.application.bot_data["runtime"]`.
- Pending mutable maps tied to transport execution model:
  - `pending_prompts`, `pending_role_ops`, `pending_bash_auth`, `bash_cwd_by_user`.
- DB-backed pending state:
  - `pending_messages`, `pending_user_fields`.

## Current High-Risk Regression Flows (must preserve behavior during migration)
1. Owner-only access enforcement in group/private handlers.
2. `/groups` and `/roles` callback navigation tree.
3. Group routing:
   - mention role,
   - `@all`,
   - orchestrator mode and delegation.
4. Pending auth and user-field replay after private input.
5. Session reset and role-level overrides.
6. Skills / prepost enablement toggles per team-role.

## Safety-Net Checklist for Stage 1+
- Keep behavior parity checks for:
  - `/groups` navigation,
  - `/roles` navigation,
  - group message routing and replies,
  - pending token flow,
  - session reset flow.
- Introduce contract tests once core<->interface types are added.
- Avoid broad signature breaks in one step; migrate with compatibility wrappers.
- Add adapter-level smoke tests before removing legacy Telegram wiring.

## Files to Watch Closely During Refactor
- `bot.py`
- `app/app_factory.py`
- `app/runtime.py`
- `app/handlers/*`
- `app/services/role_pipeline.py`
- `app/services/formatting.py`
- `app/services/plugin_pipeline.py`
- `app/services/group_reconcile.py`

## Stage 0 Outcome
- Telegram coupling map captured.
- Safety-net regression checklist defined.
- Baseline ready for Stage 1 (contracts + interface runtime loader).
