# System Map

## Основные компоненты

- `runtime_service.py` - исполняет очередь и long-running обработку.
- `api_service.py` - HTTP API (`/api/v1`) для read/write и admin.
- `telegram_service.py` - Telegram transport (thin client + event bus delivery).

## Где интерфейс встраивается

Есть 2 модели:

1. Внешний интерфейс через HTTP API.
- Ваш сервис сам вызывает `/api/v1/questions` и читает результат.
- Для realtime использовать thread event subscriptions.

2. Внутренний adapter внутри runtime.
- Реализуется по контракту `interfaces_sdk/contract.py`.
- Фабрика: `create_adapter(core_port, runtime, config)`.

## Поток данных QA

1. Интерфейс отправляет `POST /api/v1/questions`.
2. API создает `question` со статусом `accepted`.
3. API публикует `thread.message.created` в `thread_events`.
4. Dispatch worker обрабатывает вопрос, создает `answer`.
5. Для ответа тоже публикуется `thread.message.created`.
6. Outbox создает `event_deliveries` и доставляет в origin/subscribers.

## Что такое primary interface

`origin_interface` у события определяет приоритетный интерфейс доставки.

- Если интерфейс отправил вопрос с `origin_interface="telegram"`, то Telegram будет первичным получателем треда.
- При этом дополнительные подписчики (`event_subscriptions`) тоже получают события.

## Где лежит бизнес-логика маршрутизации ролей

`app/application/use_cases/qa_api.py`:

- Явный `team_role_id` в запросе имеет приоритет.
- Если `team_role_id` не передан, используется tag-routing по тексту.
- Если тега нет, пробуется orchestrator fallback (если ровно один активный orchestrator).

## Обязательные поля роли перед запуском

Валидация в `qa_api.py`:

- `working_dir` обязателен, если у provider есть `user_fields.working_dir`.
- `root_dir` обязателен, если у роли есть включенный skill c префиксом `fs.`.

При отсутствии полей `POST /questions` возвращает validation error.
