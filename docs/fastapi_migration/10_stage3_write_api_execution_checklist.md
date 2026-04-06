# 10. Stage 3 v1 Write API Execution Checklist

Дата фиксации: **2026-04-05**

## 1. Цель
- Зафиксировать baseline и критерии приёмки первой поставки Stage 3 (write/mutation/orchestration API).
- Закрепить обязательные блокеры для статуса `Stage 3 v1 = GO`.
- Подтвердить границы: additive-only для API v1 и отсутствие Telegram UX-регрессий.

## 2. Baseline (на входе Stage 3)
- Stage 2 read-only: **закрыт (GO)**.
- Инвентарь операций и stage-разбивка: `docs/fastapi_migration/08_telegram_operations_inventory.md`.
- Расширения Stage 2 read API и quality gates: **закрыты (GO)**.
- Базовый контракт Stage 3:
  - owner-only authz для всех write endpoint-ов;
  - единый error envelope;
  - синхронные write-операции (без `202/async queue API`);
  - rollback policy: DB transaction + единый error contract, без compensating workflows.
- Контрактная спецификация write endpoint-ов:
  - `docs/fastapi_migration/11_stage3_write_api_contracts.md`.

## 3. Scope Stage 3 v1
- `PATCH /api/v1/teams/{team_id}/roles/{role_id}`:
  - `enabled`, `model_override`, display/prompt overrides;
  - orchestrator-флаг там, где применимо в текущем домене.
- `POST /api/v1/teams/{team_id}/roles/{role_id}/reset-session`
- `DELETE /api/v1/teams/{team_id}/roles/{role_id}` (deactivate binding)
- `PUT /api/v1/team-roles/{team_role_id}/skills/{skill_id}` (enable/disable)
- `PUT /api/v1/team-roles/{team_role_id}/prepost/{prepost_id}` (enable/disable/config-lite при наличии доменной поддержки)

## 4. Обязательные acceptance criteria (blockers)

### B1. Endpoint реализация
- [x] Все endpoint-ы из раздела 3 реализованы в `/api/v1`.
- [x] HTTP-слой переиспользует application/use-case слой без дублирования доменной логики.

### B2. Статусы и конфликтная семантика
- [x] Статусы ошибок единообразны:
  - `404` not found;
  - `409` domain conflict / runtime busy / state conflict;
  - `422` validation/invariant;
  - `401/403` authz.
- [x] Статусы успеха зафиксированы по endpoint-контракту (`200/204`).

### B3. Idempotency
- [x] `Idempotency-Key` обязателен для:
  - `POST .../reset-session`;
  - `DELETE .../roles/{role_id}`.
- [x] `PATCH/PUT` операции естественно идемпотентны по целевому состоянию.
- [x] Повторные запросы не создают побочных мутаций сверх первого успешного применения.

### B4. Authz и error envelope
- [x] Owner-only authz включён для всех write endpoint-ов.
- [x] Для ошибок используется единый envelope без ad-hoc форматов.

### B5. Transaction boundaries
- [x] Подтверждены UoW boundaries для:
  - `reset session`;
  - `deactivate binding`;
  - `skill toggle`;
  - `prepost toggle/config-lite`;
  - runtime status transitions (если затрагиваются).
- [x] Границы покрыты тестами атомарности/rollback.

### B6. Quality gates (blocking)
- [x] Unit + integration + contract tests для write endpoint-ов.
- [x] Отдельные idempotency tests.
- [x] Authz tests (`200/401/403`).
- [x] Error envelope/status mapping tests.
- [x] Regression Telegram UX tests (без регрессий).
- [x] OpenAPI snapshot обновлён и блокирующий.

### B7. CI merge gate
- [x] Добавлен обязательный CI job: **`stage3_write_api_gates`**.
- [x] Локальный entrypoint для CI-gates: `scripts/stage3_write_api_gates.sh`.
- [x] `stage3_write_api_gates` стабильно зелёный.

### B8. Документация и sign-off
- [x] Обновлены docs/runbook по Stage 3 write API.
- [x] Задокументированы idempotency и conflict semantics.
- [x] Подготовлен sign-off: что сделано, что вне scope, остаточные риски.

## 5. Non-blocking (после Stage 3 v1)
- [ ] Async write API/queue endpoints (`202 + polling`).
- [ ] Compensating workflows поверх транзакционной модели.
- [ ] Расширенная матрица прав beyond owner-only.

## 6. Definition of Done (Stage 3 v1)
- Все блокеры B1-B8 закрыты.
- `stage3_write_api_gates` зелёный.
- OpenAPI snapshot проходит как blocking check.
- Telegram UX без регрессий.
- Docs/runbook/sign-off обновлены и консистентны.

Статус: **DONE (2026-04-05)**.
