# Docs Update Stage 1: Impact Mapping (LTC-12/13/14/17)

Date: 2026-03-14

## Goal
Define exact documentation files to update based on implemented behavior, without changelog sections.

## Audit Summary
- `docs` and `confluence_docs` already contain partial coverage for LTC-12 and LTC-17.
- Coverage for LTC-13 and LTC-14 is mostly implicit and not formalized in architecture/development pages.
- Several pages still describe pre-LTC-17 startup/layering (`bot.py` + `app_factory`) without interface runner focus.
- Operational runbooks/checklists for LTC-13/14/17 exist in `docs/temp`, but are not reflected in stable docs sections.

## Target Files: `docs/`

1. `docs/overview.md`
- Why update: currently mentions Telegram lifecycle and handler registration as primary startup path.
- Required updates:
  - reflect `InterfaceRuntimeRunner` startup model,
  - reflect `team` abstraction (LTC-14),
  - reflect role layering (`master-role` + team bindings/overrides from LTC-13),
  - keep LTC-12 identity/hot-reload behavior as source of truth.

2. `docs/dev.md`
- Why update: layering text is partially outdated and lacks explicit run/verify commands for LTC-12/13/14/17 combined behavior.
- Required updates:
  - architecture layering with `app/interfaces/*`, `app/core/use_cases/*`,
  - commands for startup/validation/smoke,
  - explicit known issues + out-of-scope notes.

3. `docs/bot-ui.md`
- Why update: UI semantics changed by LTC-13/14 (team-oriented bindings and master-role workflow).
- Required updates:
  - `/groups` as team binding view (Telegram alias),
  - `/roles` as master-role management view,
  - callbacks behavior aligned with team-role bindings.

4. `docs/ltc-12-roles-json.md`
- Why update: validate and complete with final runtime behavior and known limitations.
- Required updates:
  - reinforce basename identity rule,
  - include run/verify commands from current toolchain,
  - document non-blocking legacy test issue context.

5. `docs/ltc-17-interface-sdk.md`
- Why update: include final state after runner switch and kit/module artifacts.
- Required updates:
  - mention `app/interfaces/telegram` module artifacts,
  - mention `interface_module_kit`,
  - include practical check commands.

6. `docs/index.md`
- Why update: add stable links if new stable pages are introduced during stages 2-3.

## Target Files: `confluence_docs/`

1. `confluence_docs/20-architecture/20-1-system-architecture-overview.md`
- Why update: still positions Telegram as primary architecture without clear interface-runtime first framing.

2. `confluence_docs/20-architecture/20-2-runtime-context-and-core-components.md`
- Why update: misses interface runtime fields and interface runner role.

3. `confluence_docs/20-architecture/20-4-data-model-and-storage-sqlite-entities.md`
- Why update: requires explicit LTC-13/LTC-14 narrative for team/team_role/session keys and compatibility constraints.

4. `confluence_docs/20-architecture/20-6-runtime-flows.md`
- Why update: needs startup/runtime flow alignment with interface runner and adapter lifecycle.

5. `confluence_docs/20-architecture/20-7-ltc-12-role-json-catalog-and-runtime-behavior.md`
- Why update: verify final behavior details and add operational checks.

6. `confluence_docs/20-architecture/20-8-interface-runtime-and-contracts.md`
- Why update: align with finalized module kit + telegram module artifacts + known limitations.

7. `confluence_docs/20-architecture/_index.md`
- Why update: ensure section scope explicitly includes LTC-13 and LTC-14 (currently only LTC-12 and LTC-17 called out).

8. `confluence_docs/10-product-and-user-flows/10-1-bot-ui-in-telegram.md`
9. `confluence_docs/10-product-and-user-flows/10-2-group-role-management.md`
- Why update: align user-flow docs with master-role + team-role bindings and team abstraction.

10. `confluence_docs/50-development/50-2-codebase-structure-and-layering.md`
11. `confluence_docs/50-development/50-4-local-validation-and-smoke-tests.md`
12. `confluence_docs/50-development/50-6-role-json-agent-guide.md`
13. `confluence_docs/50-development/50-7-interface-sdk-developer-guide.md`
- Why update: align development workflow, commands, known issues, and scope boundaries with implemented state.

14. `confluence_docs/50-development/_index.md`
- Why update: ensure subsection descriptions match updated page content.

## Known Issues To Document (per requirements)
- Non-blocking legacy regression from broader suite:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`
- Environment-dependent limitation:
  - Telegram adapter runtime/smoke requires `python-telegram-bot` package in execution environment.

## Out-of-Scope Notes To Document
- No multi-interface runtime mode (`runtime_mode=single` only).
- Core event dispatch abstraction is scaffolded; Telegram transport still uses existing handlers internally.
- No unified cross-LTC summary page (explicitly out by requirement).

## Stage 1 Result
- Impact mapping completed.
- File update plan is ready for Stage 2 (`docs`) and Stage 3-4 (`confluence_docs`).
