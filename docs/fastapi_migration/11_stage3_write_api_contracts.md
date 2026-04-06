# 11. Stage 3 v1 Write API Contracts

Дата фиксации: **2026-04-05**

## 1. Цель
- Зафиксировать контракт Stage 3 v1 для write/mutation/orchestration endpoint-ов.
- Синхронизировать request/response DTO, status semantics, error envelope и idempotency.
- Использовать документ как source-of-truth для реализации и тестов `stage3_write_api_gates`.

## 2. Общие правила контракта
- Префикс: `/api/v1`.
- Authz: owner-only для всех write endpoint-ов.
- Success statuses: `200` или `204` по endpoint-контракту.
- Error statuses: `401`, `403`, `404`, `409`, `422`.
- Единый error envelope:
```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": {},
    "retryable": false
  }
}
```
- Синхронные write-операции: без `202`, без async queue API.
- Совместимость: additive-only, без breaking для уже реализованного Stage 2.

## 3. Idempotency semantics
- Обязательный `Idempotency-Key` (header) для:
  - `POST /api/v1/teams/{team_id}/roles/{role_id}/reset-session`
  - `DELETE /api/v1/teams/{team_id}/roles/{role_id}`
- Поведение при повторе с тем же ключом и тем же payload:
  - вернуть тот же логический результат (без повторной побочной мутации).
- Поведение при повторе с тем же ключом и другим payload:
  - `422 validation.invalid_input` (`idempotency payload mismatch`).
- `PATCH/PUT`:
  - естественная идемпотентность по целевому состоянию (повтор не меняет результат).

## 4. Endpoint contracts

### 4.1 PATCH `/api/v1/teams/{team_id}/roles/{role_id}`
Назначение: обновить состояние и overrides team-role.

Request body DTO (все поля optional, но хотя бы одно поле обязательно):
```json
{
  "enabled": true,
  "is_orchestrator": false,
  "model_override": "provider:model",
  "display_name": "string",
  "system_prompt_override": "string",
  "extra_instruction_override": "string",
  "user_prompt_suffix": "string",
  "user_reply_prefix": "string"
}
```

Success response (`200`):
```json
{
  "team_id": 1,
  "role_id": 2,
  "team_role_id": 10,
  "enabled": true,
  "is_active": true,
  "mode": "normal",
  "is_orchestrator": false,
  "model_override": "provider:model",
  "display_name": "string",
  "system_prompt_override": "string",
  "extra_instruction_override": "string",
  "user_prompt_suffix": "string",
  "user_reply_prefix": "string"
}
```

Status mapping:
- `200` updated (включая no-op при повторе того же target-state).
- `401/403` owner authz.
- `404` team/role binding not found.
- `409` domain/runtime state conflict (например, конфликт orchestrator state).
- `422` invalid input/invariant.

### 4.2 POST `/api/v1/teams/{team_id}/roles/{role_id}/reset-session`
Назначение: reset session для связки team-role.

Headers:
- `Idempotency-Key`: required.

Request body DTO:
```json
{
  "telegram_user_id": 123456789
}
```

Success response (`200`):
```json
{
  "ok": true,
  "team_id": 1,
  "role_id": 2,
  "telegram_user_id": 123456789,
  "team_role_id": 10,
  "operation": "reset_session"
}
```

Status mapping:
- `200` reset applied / idempotent replay.
- `401/403` owner authz.
- `404` team/role binding not found.
- `409` runtime/domain conflict.
- `422` invalid input/invariant.

### 4.3 DELETE `/api/v1/teams/{team_id}/roles/{role_id}`
Назначение: deactivate team-role binding (без физического destructive delete).

Headers:
- `Idempotency-Key`: required.

Request body DTO:
```json
{
  "telegram_user_id": 123456789
}
```

Success response:
- `204` No Content.

Status mapping:
- `204` deactivated / idempotent replay.
- `401/403` owner authz.
- `404` team/role binding not found.
- `409` domain/runtime conflict.
- `422` invalid input/invariant.

### 4.4 PUT `/api/v1/team-roles/{team_role_id}/skills/{skill_id}`
Назначение: включение/выключение skill для team-role.

Request body DTO:
```json
{
  "enabled": true
}
```

Success response (`200`):
```json
{
  "team_role_id": 10,
  "skill_id": "skill.id",
  "enabled": true,
  "config": {}
}
```

Status mapping:
- `200` upsert/toggle applied (идемпотентно по target-state).
- `401/403` owner authz.
- `404` team-role/skill not found.
- `409` state conflict.
- `422` invalid input/invariant.

### 4.5 PUT `/api/v1/team-roles/{team_role_id}/prepost/{prepost_id}`
Назначение: включение/выключение и config-lite для pre/post processing.

Request body DTO:
```json
{
  "enabled": true,
  "config": {}
}
```

Success response (`200`):
```json
{
  "team_role_id": 10,
  "prepost_id": "prepost.id",
  "enabled": true,
  "config": {}
}
```

Status mapping:
- `200` upsert/toggle/config-lite applied (идемпотентно по target-state).
- `401/403` owner authz.
- `404` team-role/prepost not found.
- `409` state conflict.
- `422` invalid input/invariant.

## 5. Error code guidance (domain/app -> API)
- `storage.not_found` -> `404`
- `runtime.busy_conflict` -> `409`
- `conflict.already_exists` -> `409`
- `validation.invalid_input` -> `422`
- `auth.unauthorized` -> `401/403` (по контексту authz)
- `internal.unexpected` -> `500` (fallback, не целевой бизнес-статус для контрактных кейсов)

## 6. Тестовые ожидания для `stage3_write_api_gates`
- Contract tests: request/response DTO shape по каждому endpoint.
- Status tests: `200/204/401/403/404/409/422`.
- Idempotency tests:
  - `Idempotency-Key` required где обязателен;
  - replay с тем же ключом не приводит к повторной мутации.
- Authz tests: owner vs missing/non-owner.
- Error envelope tests: единая форма ошибки для всех write endpoint-ов.
- OpenAPI snapshot: blocking.
- Telegram UX regression: обязательный набор без деградации текущего поведения.
