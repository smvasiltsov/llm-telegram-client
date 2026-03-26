# LTC-14: Team Abstraction Instead of Telegram Group Domain

## Scope
LTC-14 переводит доменную модель с `group` на `team`:
- `team` — каноническая бизнес-сущность,
- Telegram group/chat — транспортный binding через `team_bindings`.

## Архитектурный результат
- Роли, маршрутизация, сессии и pending/auth flows работают по `team_id`.
- Telegram остается интерфейсом, а не доменной сущностью.
- UX-команды `/groups` сохраняются как алиас для team bindings.

## Данные и runtime
- Основные таблицы: `teams`, `team_bindings`, `team_roles`.
- Сессии: team-scoped (`user_role_sessions` через team-role связь).
- Skills/prepost: team-role scoped.

## Команды проверки
- `python3 scripts/team_rollout_readiness.py --config config.json`
- `python3 -m unittest tests.test_storage_team_compat tests.test_pending_store_team_dual_read tests.test_team_migration_cleanup`

## Операционная проверка
- См. runbook: `docs/temp/ltc-14-pure-team-rollout-rollback-runbook.md`
- См. manual checklist: `docs/temp/ltc-14-pure-team-manual-validation-checklist.md`

## Known Issues
- Legacy additive migration test может падать в текущем окружении:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Мульти-интерфейсный runtime режим (`runtime_mode=multi`).
- Удаление всех legacy alias-команд в Telegram UX.
