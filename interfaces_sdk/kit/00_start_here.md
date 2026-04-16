# Start Here

## 1) Поднять сервисы локально

```bash
cd /opt/llm/llm-telegram-client-in-dev
source .venv/bin/activate
python3 runtime_service.py
```

В другом терминале:

```bash
cd /opt/llm/llm-telegram-client-in-dev
source .venv/bin/activate
python3 api_service.py
```

Проверка:

```bash
curl -sS http://127.0.0.1:8091/health/ready
curl -sS http://127.0.0.1:8080/openapi.json | head
```

## 2) Базовый auth context

Все API-вызовы интерфейса должны передавать:

- Header `X-Owner-User-Id: <owner_user_id>`
- Header `Idempotency-Key: <unique key>` для write-запросов
- Header `X-Correlation-Id: <trace id>` рекомендуется всегда

## 3) Минимальный flow интерфейса

1. Получить команды: `GET /api/v1/teams`
2. Получить роли команды: `GET /api/v1/teams/{team_id}/roles`
3. Отправить вопрос: `POST /api/v1/questions`
4. Для асинхронного ответа:
- либо polling `GET /api/v1/questions/{question_id}/answer`
- либо подписка на события через admin event API

## 4) Важные правила идентификаторов

- `role_id` использовать только для master-role операций (`PATCH /roles/{role_id}`, bind в команду).
- Для роли внутри команды использовать только `team_role_id`.

## 5) Быстрая проверка отправки вопроса

```bash
OWNER_ID=<owner>
TEAM_ID=<team_id>
TEAM_ROLE_ID=<team_role_id>

curl -sS -X POST "http://127.0.0.1:8080/api/v1/questions" \
  -H "Content-Type: application/json" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Idempotency-Key: sdk-smoke-$(date +%s)" \
  -d "{\"team_id\": ${TEAM_ID}, \"team_role_id\": ${TEAM_ROLE_ID}, \"text\": \"SDK smoke\", \"origin_interface\": \"my-interface\"}"
```

## 6) Если ответ не приходит

Сразу проверить:

- `GET /api/v1/admin/thread-events?thread_id=...`
- `GET /api/v1/admin/event-deliveries?event_id=...`
- `GET /api/v1/admin/event-deliveries/summary`

Детали в `06_observability_ops.md` и `07_troubleshooting.md`.
