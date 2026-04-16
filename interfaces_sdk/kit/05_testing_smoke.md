# Testing And Smoke

## Минимальные smoke-проверки интерфейса

1. `POST /questions` возвращает `202`.
2. `GET /questions/{id}/status` переходит в terminal state (`answered|failed|timeout|cancelled`).
3. `GET /questions/{id}/answer` возвращает `200` после готовности.
4. При одинаковом `Idempotency-Key` нет дубля question.
5. События видны в `GET /admin/thread-events`.
6. Доставки видны в `GET /admin/event-deliveries`.

## Smoke-команды

```bash
OWNER_ID=700

curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/teams?limit=1&offset=0"

curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/teams/3/roles?include_inactive=true"
```

```bash
curl -sS -X POST "http://127.0.0.1:8080/api/v1/questions" \
  -H "Content-Type: application/json" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Idempotency-Key: test-$(date +%s)" \
  -d '{"team_id":3,"team_role_id":12,"text":"smoke","origin_interface":"my-interface"}'
```

```bash
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/thread-events?team_id=3&limit=20"
curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/admin/event-deliveries/summary"
```

## Что автоматизировать в CI

- Контракт интерфейсного адаптера: `scripts.interface_sdk_smoke`.
- Happy path question->answer.
- Проверку required fields (`working_dir`, `root_dir`).
- Event delivery without duplicates для целевого интерфейса.
