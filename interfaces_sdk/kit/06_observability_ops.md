# Observability And Ops

## Слой 1: event log

API:

- `GET /api/v1/admin/thread-events?thread_id=...`
- `GET /api/v1/admin/thread-events/trace?event_id=...`

Используй для ответа на вопрос: событие вообще было опубликовано?

## Слой 2: delivery state

API:

- `GET /api/v1/admin/event-deliveries?event_id=...`
- `GET /api/v1/admin/event-deliveries/summary`

Статусы:

- `pending`
- `in_progress`
- `retry_scheduled`
- `delivered`
- `skipped`
- `failed_dlq`

Используй для ответа на вопрос: публикация была, но доставка сломалась?

## Слой 3: метрики/логи/корреляция

Ключевые метрики:

- `events_published`
- `deliveries_ok`
- `deliveries_failed`
- `delivery_lag_ms`
- `dlq_size`
- `runtime_queue_depth` (`queue_name=qa_dispatch_bridge`)

Типовые логгеры:

- `api.thread_events`
- `api.thread_outbox`
- `api.qa_dispatch_bridge`
- `bot.metrics`

## Корреляция

Передавай `X-Correlation-Id` в каждый входящий запрос интерфейса.

Дальше trace собирается по:

- `correlation_id`
- `thread_id`
- `question_id`
- `event_id`
- `delivery_id`

## Операционные действия

- Застрявшая доставка: `POST /admin/event-deliveries/{id}/retry`
- Пропустить проблемную: `POST /admin/event-deliveries/{id}/skip`
- Вернуть из DLQ: `POST /admin/event-deliveries/{id}/dlq-requeue`

## Нормально ли частый INFO

Частые INFO у `bot.metrics` и outbox/dispatch нормальны при активной обработке.
Считать проблемой только при росте `failed_dlq` и/или устойчивом росте `delivery_lag_ms`.
