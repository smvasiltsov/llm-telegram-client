# 13. Stage 3 v1 Sign-off

Дата: **2026-04-05**

## 1. Решение
- Stage 3 v1 write API: **GO**.
- Обязательный merge gate: **`stage3_write_api_gates`**.
- Telegram-путь: **backward compatible** (регрессии UX не выявлены в обязательном regression наборе).

## 2. Что сделано
- Реализован application/use-case write слой для Stage 3 v1:
  - `PATCH /api/v1/teams/{team_id}/roles/{role_id}`
  - `POST /api/v1/teams/{team_id}/roles/{role_id}/reset-session`
  - `DELETE /api/v1/teams/{team_id}/roles/{role_id}`
  - `PUT /api/v1/team-roles/{team_role_id}/skills/{skill_id}`
  - `PUT /api/v1/team-roles/{team_role_id}/prepost/{prepost_id}`
- Добавлены явные transaction boundaries и проверка UoW для обязательных сценариев.
- Добавлена idempotency-обработка:
  - обязательный `Idempotency-Key` для `reset-session` и `deactivate`.
- Подключён HTTP adapter `/api/v1`:
  - owner-only authz;
  - единый error envelope;
  - status mapping по контракту (`200/204/401/403/404/409/422`).
- Обновлён blocking OpenAPI snapshot с write path/method.
- Добавлены quality gates и CI:
  - `scripts/stage3_write_api_gates.sh`
  - `.github/workflows/stage3_write_api_gates.yml`

## 3. Что вне scope
- Async queue/write API (`202 + polling`).
- Compensating workflows.
- Расширенная RBAC/ABAC authz beyond owner-only.
- Rate limiting.

## 4. Idempotency / conflict / boundary semantics (зафиксировано)
- Idempotency:
  - `POST reset-session` и `DELETE deactivate` требуют `Idempotency-Key`.
  - Replay с тем же ключом и payload не выполняет повторную мутацию.
  - Replay с тем же ключом и другим payload -> `422 validation.invalid_input`.
- Conflict/status mapping:
  - `404` not found;
  - `409` domain/state conflict;
  - `422` validation/invariant;
  - `401/403` owner authz.
- Transaction boundaries:
  - reset session / deactivate binding / skill toggle / prepost toggle-config / runtime transitions.

## 5. Остаточные риски
- Idempotency store в v1 — in-memory runtime scope; для multi-instance прод-контура потребуется внешнее персистентное хранилище ключей.
- Конфликтная семантика `409` требует дисциплины при расширении write surface, чтобы не возникал дрейф кодов между endpoint-ами.
- При дальнейшем расширении write API нужен строгий контроль additive-compatible DTO/OpenAPI.

## 6. Артефакты
- Checklist Stage 3 v1:
  - `docs/fastapi_migration/10_stage3_write_api_execution_checklist.md`
- Контракты Stage 3 v1:
  - `docs/fastapi_migration/11_stage3_write_api_contracts.md`
- Runbook Stage 3 v1:
  - `docs/fastapi_migration/12_stage3_v1_write_api_runbook.md`
- Gate scripts/jobs:
  - `scripts/stage3_write_api_gates.sh`
  - `.github/workflows/stage3_write_api_gates.yml`

## 7. Консистентность с Stage 2
- Stage 2 документы (`05/06/07/09`) сохраняют силу для read-only части и не конфликтуют с Stage 3:
  - Stage 2 gate остаётся обязательным в составе Stage 3 gate chain.
  - Stage 3 добавляет write surface поверх существующего `/api/v1`, не меняя базовые read контракты.
