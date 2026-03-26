# Управление ботом через Telegram

## Основной вход
- Основные разделы в личных сообщениях owner:
  - `/groups` — команды (team bindings в Telegram),
  - `/roles` — master-role каталог.

## `/roles` (master roles)
- Список ролей строится из `roles_catalog/*.json`.
- Каталог перечитывается с диска на каждый запрос (`hot-reload`).
- В списке показываются:
  - валидные роли,
  - ошибки чтения/валидации JSON (отдельным блоком).

### Правила identity
- identity роли берется только из имени файла (`basename .json`).
- валидный basename: `^[a-z0-9_]+$`.
- `role_name` внутри JSON не используется как identity (metadata only).

### Ошибки каталога в UI
Примеры отображаемых ошибок:
- некорректное имя файла,
- дубликат роли по case-fold,
- mismatch между `role_name` в JSON и именем файла,
- битый JSON.

## `/groups` (team role bindings)
- Внутри команды показываются только активные привязки ролей.
- Добавление роли в команду выполняется из master-role списка.
- Если файл роли удален или переименован, старые привязки этой identity деактивируются при refresh.
- Создание роли "с нуля" в контексте команды не используется как primary flow.

## Роль в карточке команды
В карточке привязанной роли доступны:
- Skills,
- Pre/Post Processing,
- системный промпт override,
- инструкция к сообщениям override,
- инструкция для реплаев override,
- LLM‑модель override,
- переименование display name,
- сброс сессии,
- удаление привязки роли из команды.

## Как бот отвечает
- В группах бот реагирует только на сообщения владельца.
- Команды управления работают только в личке.
- Master defaults для роли берутся из JSON-каталога.
- Team overrides применяются поверх master defaults.

## Команды проверки UI-потоков
- `python3 -m unittest tests.test_ltc12_manual_json_bind_runtime tests.test_ltc12_hot_reload_full_scenario tests.test_ltc13_storage_team_role_api`
- Ручной smoke:
  - `/roles` (список + карточка + привязка к команде),
  - `/groups` (список команд + карточка привязки роли),
  - callbacks (toggle/mode/model/reset/delete binding).

## Known Issues
- Неблокирующий legacy-тест в broader suite:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.
