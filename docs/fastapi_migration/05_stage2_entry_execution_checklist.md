# 05. Stage 2 Entry Execution Checklist

## 1. Цель
- Зафиксировать baseline перед стартом Stage 2 (read-only API) и критерии приёмки.
- Разделить пункты на:
  - блокеры для статуса `Stage 2 start = GO`;
  - non-blocking улучшения (можно закрывать после старта Stage 2).
- Для первой поставки Stage 2 v1 зафиксировать scope:
  - только `/api/v1` read-only adapter;
  - strict DTO/OpenAPI contract;
  - полная обратная совместимость Telegram-пути.

## 2. Baseline (на момент фиксации)
- Stage 1 exit: **GO (9.4/10)**.
- Stage 2 start: **GO (9.1/10)**.
- Источник baseline: `docs/fastapi_migration/02_api_readiness_assessment.md`.
- Окно первой поставки Stage 2 v1:
  - endpoint scope: `GET /api/v1/teams`, `GET /api/v1/teams/{team_id}/roles`, `GET /api/v1/teams/{team_id}/runtime-status`;
  - write API вне scope;
  - Telegram UX/поведение не изменяется.

## 3. Критерий приёмки этапа
- `Stage 1 exit = GO` подтверждён по чеклисту ниже.
- `Stage 2 start = GO` подтверждён после прохождения всех блокеров в CI.
- Дата sign-off: **2026-04-05**.
- Подтверждение прогона: `scripts/stage2_read_api_gates.sh` — **пройдено без skip**.
- Обязательный merge-gate для Stage 2 v1: **`stage2_read_api_gates`**.
- OpenAPI snapshot для Stage 2 v1: **blocking**.

## 4. Блокеры Stage 2 GO (обязательные)

### B1. Pre-Stage2 refactoring закрыт для критичных веток
- [x] В `handlers` оставлен transport/UX glue; критичная доменная логика вынесена в application/use-cases для:
  - `group/private dispatch`;
  - `role admin` read/view;
  - `pending replay` orchestration.
- Проверка:
  - code review по `app/handlers/*`, `app/application/use_cases/*`;
  - точечные regression tests на отсутствие UX-регрессий Telegram.

### B2. Unified error mapping на application/API boundary
- [x] Единый контракт ошибок используется в read-only API path: `code/message/details/http_status`.
- [x] Нет ad-hoc HTTP error форматов в endpoint-ах.
- Проверка:
  - unit tests на mapper;
  - integration tests endpoint response/error shape.

### B3. Transaction boundaries формализованы и тестируемы
- [x] Явно закреплены и проверены UoW-границы для:
  - `reset session`;
  - `delete/deactivate binding`;
  - `pending replay`;
  - `skill toggle`;
  - `runtime status transitions`.
- Проверка:
  - единый registry границ в `app/application/use_cases/transaction_boundaries.py`;
  - тесты атомарности/rollback;
  - тесты write-uow-guard.

### B4. Минимальный read-only FastAPI каркас реализован
- [x] Добавлен FastAPI app factory и роутеры (без write API).
- [x] Реализованы endpoint-ы:
  - `GET /api/v1/teams` (с pagination);
  - `GET /api/v1/teams/{team_id}/roles`;
  - `GET /api/v1/teams/{team_id}/runtime-status`.
- Проверка:
  - endpoint contract/integration tests зелёные.

### B5. Owner-only authz dependency для HTTP
- [x] Dependency для owner-only авторизации включена в read-only API.
- [x] Поведение на неавторизованный доступ консистентно по статус-коду/формату ошибки.
- Проверка:
  - authz tests на 200/401/403 сценарии.

### B6. DTO/Schema consistency quality gates
- [x] DTO contract tests проходят.
- [x] Endpoint response shape tests проходят.
- [x] OpenAPI snapshot test блокирующий для Stage 2 v1.
- [x] DTO v1 зафиксированы как strict contract (`extra=forbid`, shape validation).
- Проверка:
  - tests на `app/interfaces/api/schemas/*`;
  - tests на сериализацию ответов endpoint-ов.
  - tests на OpenAPI snapshot.

### B7. CI gate для Stage 2
- [x] Добавлен отдельный набор/джоб `stage2_read_api_gates` (обязательный merge gate), который включает:
  - критичный runtime regression;
  - read-only API contract/integration tests;
  - authz dependency tests;
  - DTO/response shape tests.
- Локальный entrypoint для джоба: `scripts/stage2_read_api_gates.sh`.
- CI workflow: `.github/workflows/stage2_read_api_gates.yml`.
- Критерий:
  - зелёный `stage2_read_api_gates` => поставка Stage 2 v1 готова к merge/release.

## 5. Non-blocking (желательно, но не блокирует старт Stage 2)
- [ ] Расширенные read-only endpoint-ы за пределами минимального набора.
- [ ] Дополнительные observability метрики API уровня.
- [ ] Дальнейшая декомпозиция `RuntimeContext` (после запуска Stage 2).
- [ ] Rate limiting (вынесено в следующую итерацию).

## 6. Telegram UX safety (жёсткий контракт)
- [x] Тексты/кнопки Telegram не ломаются.
- [x] Любые точечные правки UX обоснованы и покрыты smoke/regression тестами.

## 7. Definition of Done для этапа
- Все пункты раздела 4 закрыты.
- CI `stage2_read_api_gates` зелёный.
- OpenAPI snapshot проходит как blocking check.
- Есть короткий runbook запуска API отдельно от Telegram процесса.
- Зафиксирован статус:
  - `Stage 1 exit = GO`;
  - `Stage 2 start = GO`.
