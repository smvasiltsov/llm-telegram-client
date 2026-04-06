# 07. Stage 2 v1 Sign-off

Дата: **2026-04-05**

## 1. Решение
- Stage 2 v1 read-only API: **GO**.
- Обязательный merge gate: **`stage2_read_api_gates`**.
- Telegram-путь: **backward compatible** (UX/поведение без регрессий по целевым regression наборам).

## 2. Что сделано
- Стабилизирован HTTP adapter `/api/v1` как отдельный interface layer:
  - router + dependencies + unified error mapping + owner-only authz.
- Реализован endpoint scope v1:
  - `GET /api/v1/teams` (pagination + meta),
  - `GET /api/v1/teams/{team_id}/roles`,
  - `GET /api/v1/teams/{team_id}/runtime-status`.
- Введены transport-политики:
  - `X-Correlation-Id` generate/propagate,
  - базовые API метрики (endpoint/status/latency).
- Зафиксирован strict DTO/OpenAPI contract:
  - DTO shape strict (`extra=forbid`),
  - OpenAPI snapshot как blocking check.
- Добавлен e2e smoke на поднятие app/runtime для read-only API.

## 3. Что вне scope
- Write API (Stage 3+).
- Rate limiting (следующая итерация).
- Расширение endpoint scope за пределами 3 read endpoint-ов v1.

## 4. Остаточные риски
- Ограничение текущей dispatch-модели (single-instance/single-runner) остаётся эксплуатационным constraint.
- Без rate limiting API защищён только owner-only authz и perimeter controls.
- Дальнейшее расширение API требует сохранения strict DTO/OpenAPI backward compatibility.

## 5. Артефакты
- Чеклист и критерии Stage 2 v1:
  - `docs/fastapi_migration/05_stage2_entry_execution_checklist.md`
- Чеклист расширения read API (catalog/errors/sessions + UI/API rationale):
  - `docs/fastapi_migration/09_stage2_read_api_extension_checklist.md`
- Runbook запуска API отдельно от Telegram:
  - `docs/fastapi_migration/06_stage2_v1_api_runbook.md`
- Gate scripts:
  - `scripts/stage2_gates.sh`
  - `scripts/stage2_read_api_gates.sh`
- CI workflow:
  - `.github/workflows/stage2_read_api_gates.yml`

## 6. Addendum: Stage 2 read API extension (2026-04-05)
- Статус поставки расширения (`roles/catalog`, `roles/catalog/errors`, `teams/{team_id}/sessions`, `include_inactive`, `is_orchestrator`): **GO**.
- Формат совместимости: **additive-only**, без breaking изменений текущих endpoint-ов.
- Quality gates: **GO** (`stage2_read_api_gates`, blocking OpenAPI snapshot, контрактные authz/error tests).
