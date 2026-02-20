# Разработка

## Архитектурные слои
- `app/handlers/*` — только Telegram transport-слой: читают `Update/Context`, вызывают runtime/services, отправляют ответы.
- `app/services/*` — переиспользуемая бизнес-логика (форматирование, prompt-building, plugin markup, tool execution).
- `app/runtime.py` — единая точка доступа к зависимостям через `context.application.bot_data["runtime"]`.

## Добавление нового провайдера
1) Создать JSON‑файл в `llm_providers/`.
2) Описать `base_url`, `capabilities`, `endpoints`, `models`, `user_fields`.
3) Перезапустить бота.

## Локальные проверки
- Проверить загрузку провайдеров в логах.
- Создать роль и выбрать модель нового провайдера.
- Отправить сообщение в группе и получить ответ.

## Минимальная проверка после изменений
- `python3 -m py_compile bot.py app/*.py app/handlers/*.py app/services/*.py app/tools/*.py plugins/*.py`
- Smoke: `/groups`, `/tools`, `/bash ls`, групповой запрос `@role`.
- Для крупных изменений handlers/services прогонять `docs/manual-regression-checklist.md`.

## Где искать логи
Логи пишутся в терминал, где запущен `bot.py`.
