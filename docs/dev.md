# Разработка

## Архитектурные слои
- `app/handlers/*` — только Telegram transport-слой: читают `Update/Context`, вызывают runtime/services, отправляют ответы.
- `app/services/*` — переиспользуемая бизнес-логика (formatting, prompt-building, skill loop, plugin markup, tool execution).
- `app/skills/*` — model-callable skills runtime.
- `app/prepost_processing/*` — pre/post hooks runtime.
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
- `python3 -m py_compile bot.py app/*.py app/handlers/*.py app/services/*.py app/tools/*.py app/skills/*.py app/prepost_processing/*.py plugins/*.py`
- `python3 -m unittest discover -s tests -v`
- Smoke:
  - `/groups` (навигация по ролям),
  - разделы `Skills` и `Pre/Post Processing` в карточке роли,
  - групповой запрос `@role`,
  - `/bash ls` (если tools включены).

## Где искать логи
Логи пишутся в терминал, где запущен `bot.py`.
