# Universal Thread Event Bus + Outbox

## Сущности

- `thread_events` - журнал событий треда (`thread.message.created`).
- `event_subscriptions` - подписки интерфейсов по `scope` (`thread` или `team`).
- `event_deliveries` - outbox-задачи доставки с retry/DLQ.

## Что публикуется

Событие `thread.message.created` создается для:

- user-question
- role-answer
- child-question (когда ответ роли превращается в вопрос к другой роли)

Важные поля события:

- `thread_id`
- `seq` (порядок внутри треда)
- `origin_interface`
- `source_question_id`
- `parent_answer_id`
- `payload_json` (kind, text, lineage)

## Маршрутизация доставки

Outbox при создании события:

1. Доставка в `origin_interface` как primary interface.
2. Доставка всем активным подписчикам `scope=thread` и `scope=team`.
3. Дедуп по `(event_id, interface_type, target_id)`.

## Retry и DLQ

- Ошибка доставки -> `retry_scheduled` с backoff.
- После `max_attempts` -> `failed_dlq`.
- Ручные операции: `retry`, `skip`, `dlq-requeue` через admin API.

## Idempotency

- Для событий: `thread_events.idempotency_key` (unique index).
- Для доставок: `event_deliveries.idempotency_key` и уникальность delivery target.

## Для нового интерфейса

1. Всегда указывай свой `origin_interface` в `POST /questions`.
2. Создавай подписку на thread/team через admin API.
3. Потребляй события из `thread-events` и/или статус доставок из `event-deliveries`.

## Пример подписки

```bash
curl -sS -X PUT "http://127.0.0.1:8080/api/v1/admin/event-subscriptions" \
  -H "Content-Type: application/json" \
  -H "X-Owner-User-Id: 700" \
  -d '{
    "scope": "team",
    "scope_id": "3",
    "interface_type": "my-interface",
    "target_id": "channel-123",
    "mode": "mirror",
    "is_active": true
  }'
```
