# HTTP API Contract For Interfaces

Базовый префикс: `/api/v1`

## Общие правила

- Auth: `X-Owner-User-Id` обязателен.
- Write-методы: передавать `Idempotency-Key`.
- Ошибки: единый envelope `{ "error": { code, message, details, retryable } }`.
- Для роли в команде использовать `team_role_id`, не `role_id`.

## Методы по master role (`role_id`)

- `GET /roles/catalog`
- `GET /roles/catalog/errors`
- `PATCH /roles/{role_id}`
- `POST /teams/{team_id}/roles/{role_id}` (bind master role to team)

## Методы по team role (`team_role_id`)

- `GET /teams/{team_id}/roles`
- `PATCH /team-roles/{team_role_id}`
- `DELETE /team-roles/{team_role_id}`
- `POST /team-roles/{team_role_id}/reset-session`
- `PUT /team-roles/{team_role_id}/skills/{skill_id}`
- `PUT /team-roles/{team_role_id}/prepost/{prepost_id}`
- `PUT /team-roles/{team_role_id}/working-dir`
- `PUT /team-roles/{team_role_id}/root-dir`

## Методы без role scope

- `GET /teams`
- `GET /teams/{team_id}/runtime-status`
- `GET /teams/{team_id}/sessions`
- `GET /skills`
- `GET /prepost_processing_tools`
- `POST /questions`
- `GET /questions/{question_id}`
- `GET /questions/{question_id}/status`
- `GET /questions/{question_id}/answer`
- `GET /answers/{answer_id}`
- `GET /qa-journal`
- `GET /threads/{thread_id}`
- `GET /orchestrator/feed`
- `GET /runtime/dispatch-health`

## Admin event bus API

- `GET /admin/event-subscriptions`
- `PUT /admin/event-subscriptions`
- `DELETE /admin/event-subscriptions/{subscription_id}`
- `GET /admin/thread-events`
- `GET /admin/thread-events/trace?event_id=...`
- `GET /admin/event-deliveries`
- `GET /admin/event-deliveries/summary`
- `POST /admin/event-deliveries/{delivery_id}/retry`
- `POST /admin/event-deliveries/{delivery_id}/skip`
- `POST /admin/event-deliveries/{delivery_id}/dlq-requeue`

## Ключевые payload примеры

### `POST /questions`

```json
{
  "team_id": 3,
  "team_role_id": 12,
  "text": "@dev проверь модуль",
  "origin_interface": "my-interface",
  "origin_type": "user"
}
```

### `PUT /team-roles/{team_role_id}/working-dir`

```json
{
  "working_dir": "/opt/projects/repo"
}
```

### `PUT /team-roles/{team_role_id}/root-dir`

```json
{
  "root_dir": "/opt/projects/repo"
}
```

## Поведение `GET /teams/{team_id}/roles`

Возвращает готовые поля для интерфейса:

- `system_prompt`
- `extra_instructions`
- `working_dir`
- `root_dir`
- `is_active`
- `is_orchestrator`
- `skills`

Backend сам подставляет итоговые значения (base/override) в `system_prompt` и `extra_instructions`.
