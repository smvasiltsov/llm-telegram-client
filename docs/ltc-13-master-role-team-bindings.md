# LTC-13: Master Role + Team Bindings

## Scope
LTC-13 вводит раздельную модель:
- master-role (глобальная роль),
- team-role binding (привязка роли к команде с отдельным `team_role_id`).

## Модель данных
- Master-role identity: `role_name` (после LTC-12 — file-based identity из `roles_catalog`).
- Привязка к команде: таблица `team_roles`.
- Уникальный surrogate ключ привязки: `team_role_id`.

## Поведение наследования/override
- Source of truth для дефолтов: master-role (prompt/instruction/model/режим по умолчанию).
- На уровне `team_role` разрешены override:
  - `display_name`,
  - `system_prompt_override`,
  - `extra_instruction`/message/reply overrides,
  - `model_override`,
  - `enabled`, `mode`,
  - bindings skills/prepost.

## UX поведение
- `/roles` в личке owner — работа с master-role.
- `/groups` — работа с привязками роли к команде.
- Удаление роли из команды удаляет только binding (master-role не удаляется).

## Команды проверки
- `python3 -m unittest tests.test_ltc13_storage_team_role_api tests.test_ltc13_inheritance_override tests.test_ltc13_additive_migration`
- `python3 scripts/db_migration_smoke.py --db-path bot.sqlite3 --expect-table team_roles --expect-column team_roles:team_role_id --expect-column user_role_sessions:team_role_id --expect-column role_prepost_processing:team_role_id --expect-column role_skills_enabled:team_role_id`

## Known Issues
- Неблокирующий legacy-тест в broader suite:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Глубокая нормализация исторических логов.
- Полный отказ от UX-алиасов `/groups`/старых callback-форматов.
