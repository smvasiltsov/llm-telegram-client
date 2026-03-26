# Обзор проекта

Этот документ даёт краткое понимание архитектуры и ключевых сущностей.

## Структура приложения
- `bot.py` — entrypoint: загрузка конфигурации, инициализация runtime и запуск через `InterfaceRuntimeRunner`.
- `app/app_factory.py` — сборка `RuntimeContext` и сервисов.
- `app/runtime.py` — единый контейнер зависимостей (`RuntimeContext`), который хранится в `bot_data["runtime"]`.
- `app/interfaces/runtime/*` — loader/runner активного интерфейса (`runtime_mode=single`).
- `app/interfaces/telegram/*` — Telegram как отдельный интерфейсный модуль.
- `app/role_catalog.py` — загрузка и валидация master-role JSON каталога.
- `app/role_catalog_service.py` — refresh/hot-reload, identity resolve, cleanup привязок при удалении/rename файла.
- `app/handlers/` — слой Telegram-обработчиков (`/groups`, `/roles`, callbacks, group/private message flows).
- `app/core/use_cases/*` — transport-agnostic use-cases для role/team операций.
- `app/services/` — бизнес-утилиты (prompt building, formatting, role pipeline, skill loop, tool exec).
- `app/storage.py` + `app/models.py` — работа с SQLite и доменными сущностями.

## Основные сущности
- **Team** — доменная команда.
- **Team binding** — связь команды с интерфейсом (Telegram chat).
- **Master role (JSON)** — master-конфигурация роли из `roles_catalog/*.json`.
- **Team role** — привязка master-role к команде с override-полями.
- **Session** — контекст пользователя по `team + role`.

## LTC-12 (актуальная модель ролей)
- Master-role identity: только basename файла `.json`.
- Валидный basename: `^[a-z0-9_]+$`.
- Поле `role_name` в JSON не является источником identity.
- Duplicate по case-fold обрабатывается детерминированно: первый файл в стабильной сортировке побеждает, остальные идут в errors.
- `/roles` и role callbacks используют hot-reload (чтение с диска на каждый запрос).
- Валидные роли отображаются вместе с ошибками каталога.
- При удалении/переименовании файла старые `team_roles`-привязки автоматически деактивируются.

## LTC-13/LTC-14 (актуальная модель привязок)
- Master-role и team-role binding разделены.
- Привязка роли к команде имеет отдельный `team_role_id`.
- Доменная сущность — `team`; Telegram group — transport binding в `team_bindings`.
- UX алиасы `/groups` и callbacks сохраняются для совместимости, но runtime работает по `team_id`.

## LTC-17 (актуальная интерфейсная модель)
- Активный интерфейс выбирается в `config.json`:
  - `interface.active`
  - `interface.modules_dir`
  - `interface.runtime_mode=single`
- Telegram вынесен в отдельный модуль `app/interfaces/telegram`.
- Контракт core↔interface и SDK: `docs/ltc-17-interface-sdk.md`, `interface_module_kit/`.

## Где хранится состояние
SQLite хранит:
- team bindings, team role bindings, override-настройки;
- user role sessions;
- conversation history;
- provider user fields;
- role-skill / role-prepost bindings;
- observability логи (`skill_runs`, `tool_runs`).

Master-role параметры (prompt/instruction/default model) берутся из JSON-файлов, а не из master-таблицы БД как источник истины.

## Known Issues
- Неблокирующий legacy-тест:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.

## Out of Scope
- Multi-interface runtime mode (поддерживается только `single`).
