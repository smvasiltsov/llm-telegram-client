# Разработка

## Архитектурные слои
- `app/handlers/*` — только Telegram transport-слой: читают `Update/Context`, вызывают runtime/services, отправляют ответы.
- `app/core/use_cases/*` — transport-agnostic сценарии (team/role operations).
- `app/services/*` — переиспользуемая бизнес-логика (formatting, prompt-building, skill loop, plugin markup, tool execution).
- `app/skills/*` — model-callable skills runtime.
- `app/prepost_processing/*` — pre/post hooks runtime.
- `app/runtime.py` — единая точка доступа к зависимостям через `context.application.bot_data["runtime"]`.
- `app/interfaces/*` — интерфейсные адаптеры и runtime-loader (`runtime_mode=single`).
- `interfaces_sdk/*` — внешний SDK-контракт для разработки новых интерфейсов.

## LTC-12/13/14/17: быстрые команды проверки
- LTC-12 (role JSON):  
  `python3 -m unittest tests.test_role_catalog tests.test_ltc12_role_catalog_service tests.test_ltc12_hot_reload_full_scenario`
- LTC-13 (master/team-role binding):  
  `python3 -m unittest tests.test_ltc13_storage_team_role_api tests.test_ltc13_inheritance_override tests.test_ltc13_additive_migration`
- LTC-14 (team abstraction):  
  `python3 -m unittest tests.test_storage_team_compat tests.test_pending_store_team_dual_read tests.test_team_migration_cleanup`
- LTC-17 (interface runtime):  
  `python3 -m unittest tests.test_interface_runtime_registry tests.test_interface_runtime_loader tests.test_interface_runtime_runner tests.test_telegram_adapter_contract`
- Interface module kit smoke:  
  `python3 -m interface_module_kit.validator.smoke_runner --scenario all`

## Добавление нового провайдера
1) Создать JSON‑файл в `llm_providers/`.
2) Описать `base_url`, `capabilities`, `endpoints`, `models`, `user_fields`.
3) Перезапустить бота.

## Локальные проверки
- Проверить загрузку провайдеров в логах.
- Создать роль и выбрать модель нового провайдера.
- Отправить сообщение в группе и получить ответ.

## Минимальная проверка после изменений
- `python3 -m py_compile bot.py app/*.py app/handlers/*.py app/services/*.py app/tools/*.py app/skills/*.py app/prepost_processing/*.py plugins/*.py`
- `python3 -m unittest discover -s tests -v`
- Smoke:
  - `/groups` (навигация по ролям),
  - разделы `Skills` и `Pre/Post Processing` в карточке роли,
  - групповой запрос `@role`,
  - `/bash ls` (если tools включены).

## Где искать логи
Логи пишутся в терминал, где запущен `bot.py`.

## Разработка нового интерфейса
1) Создать модуль `app/interfaces/<interface_id>/adapter.py` с `create_adapter(...)`.
2) Реализовать контракт `interface_id`, `start()`, `stop()`.
3) Проверить контракт:
- `python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me`
4) Проверить свой модуль:
- `python3 -m scripts.interface_sdk_smoke app.interfaces.<interface_id>.adapter <interface_id>`
5) Включить интерфейс в `config.json` через `interface.active`.

## Known Issues
- В расширенном регрессе возможен legacy fail:
  - `tests.test_team_migration_additive.TeamMigrationAdditiveTests.test_storage_additive_team_migration_backfills_existing_group_data`.
- Для реального запуска Telegram interface adapter нужен установленный `python-telegram-bot`.

## Out of Scope
- `runtime_mode=multi` (поддерживается только `single`).
