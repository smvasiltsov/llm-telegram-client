# 29. Stage 5 Event Bus + Outbox Runbook

Дата фиксации: **2026-04-12**

## 1. Scope
- Universal Thread Event Bus:
  - публикация `thread.message.created` для:
    - `user-question`
    - `child-question`
    - `role-answer`
- Outbox delivery:
  - primary interface + subscriptions;
  - retry/backoff;
  - DLQ;
  - idempotent delivery key.
- Admin API:
  - CRUD подписок;
  - просмотр event/delivery;
  - ручные actions: retry/skip/dlq-requeue.

## 2. Data model (SQLite)
- `thread_events`
- `event_subscriptions`
- `event_deliveries`

Ключевые инварианты:
- `thread_events.idempotency_key` уникален (partial unique).
- `event_deliveries` уникален по `(event_id, interface_type, target_id)`.
- Delivery idempotency key формируется как:
  - `delivery:{event_id}:{interface_type}:{target_id}`.

## 3. Publish semantics
- Event type: `thread.message.created`.
- Обязательные поля event:
  - `thread_id`
  - `seq`
  - `origin_interface`
  - lineage в `payload_json`:
    - `source_question_id`
    - `parent_answer_id`

`origin_interface`:
- direct user question через API: `api`
- post-answer child dispatch: `qa_bridge`
- role answer event: берётся из origin исходного вопроса (fallback `qa_bridge`).

## 4. Outbox semantics
- При создании event автоматически enqueue deliveries:
  - primary target: `(origin_interface, thread_id)` если `origin_interface` заполнен;
  - активные subscriptions по `scope=thread` и `scope=team`.
- Dispatcher:
  - claim lease (`in_progress`, `lease_owner`, `lease_expires_at`);
  - success -> `delivered`;
  - failure + remaining attempts -> `retry_scheduled` + backoff;
  - failure + no attempts -> `failed_dlq`.

## 5. Admin API

### 5.1 Subscriptions
- `GET /api/v1/admin/event-subscriptions`
- `PUT /api/v1/admin/event-subscriptions`
- `DELETE /api/v1/admin/event-subscriptions/{subscription_id}`

### 5.2 Events / trace
- `GET /api/v1/admin/thread-events`
  - фильтры: `event_id`, `thread_id`, `team_id`, `limit`
- `GET /api/v1/admin/thread-events/trace?event_id=...`
  - возвращает event + связанные deliveries

### 5.3 Deliveries
- `GET /api/v1/admin/event-deliveries`
  - фильтры: `event_id`, `interface_type`, `target_id`, `status`, `limit`
  - в ответе: `lag_ms`
- `GET /api/v1/admin/event-deliveries/summary`
  - `total`, `pending`, `in_progress`, `retry_scheduled`, `delivered`, `skipped`, `failed_dlq`
  - `avg_lag_ms`, `max_lag_ms`

### 5.4 Manual actions
- `POST /api/v1/admin/event-deliveries/{delivery_id}/retry`
- `POST /api/v1/admin/event-deliveries/{delivery_id}/skip`
- `POST /api/v1/admin/event-deliveries/{delivery_id}/dlq-requeue`

`dlq-requeue` разрешён только для `status=failed_dlq`.

## 6. Observability

### 6.1 Metrics
- publish:
  - `events_published`
- outbox delivery:
  - `deliveries_ok`
  - `deliveries_failed`
  - `delivery_lag_ms`
  - `dlq_size`
- существующие outbox metrics:
  - `thread_outbox_delivery_total`
  - `thread_outbox_delivery_latency_ms`

### 6.2 Logs
- publish:
  - `thread_event_published correlation_id=... event_id=... thread_id=... seq=...`
- outbox:
  - `thread_outbox_delivery_started ...`
  - `thread_outbox_delivery_done ...`
  - `thread_outbox_delivery_failed ...`

### 6.3 Correlation
- Используется `correlation_id` на publish и delivery.
- API error envelope по-прежнему включает `details.correlation_id`.

## 7. Smoke (manual)

1. Создать subscription:
```bash
curl -sS -X PUT "http://127.0.0.1:8080/api/v1/admin/event-subscriptions" \
  -H "X-Owner-User-Id: ${OWNER_ID}" -H "Content-Type: application/json" \
  -d '{"scope":"team","scope_id":"1","interface_type":"mirror","target_id":"team-1","is_active":true}'
```

2. Создать вопрос:
```bash
curl -sS -X POST "http://127.0.0.1:8080/api/v1/questions" \
  -H "X-Owner-User-Id: ${OWNER_ID}" -H "Idempotency-Key: smoke-event-bus-1" \
  -H "Content-Type: application/json" \
  -d '{"team_id":1,"team_role_id":1,"text":"event bus smoke"}'
```

3. Проверить event и trace:
```bash
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/thread-events?limit=5"
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/thread-events/trace?event_id=<EVENT_ID>"
```

4. Проверить deliveries и summary:
```bash
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/event-deliveries?limit=20"
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/event-deliveries/summary"
```

5. Проверить manual action:
```bash
curl -sS -X POST -H "X-Owner-User-Id: ${OWNER_ID}" \
  "http://127.0.0.1:8080/api/v1/admin/event-deliveries/<DELIVERY_ID>/retry"
```

## 8. Rollout checklist (short)
- [ ] Применены additive schema changes (без удаления старых контрактов).
- [ ] Включён outbox dispatcher на API/runtime процессах.
- [ ] Smoke пройден: publish -> delivery -> trace/summary.
- [ ] Проверены manual actions (`retry/skip/dlq-requeue`).
- [ ] Проверены метрики и structured logs с `correlation_id`.
- [ ] План rollback: отключить dispatcher и оставить существующий QA flow.
