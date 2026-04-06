# 15. Stage 4 Runtime/API Hardening Checklist

Дата фиксации baseline: **2026-04-05**

## 1. Цель
- Зафиксировать baseline и обязательный checklist для закрытия Stage 4 (Runtime/API hardening).
- Подтвердить рамки этапа: observability, single-instance policy, runbook, smoke/integration readiness.
- Задать блокирующие критерии `Stage 4 = GO`.

## 2. Baseline (на входе Stage 4)
- Stage 2: **GO** (read-only API закрыт).
- Stage 3 v1: **DONE** (write API закрыт).
- Stage 5: добавлен в roadmap, реализация отложена до закрытия Stage 4.
- Source roadmap: `docs/fastapi_migration/04_migration_roadmap_and_risks.md`.

## 3. Scope Stage 4
- В scope:
  - correlation/trace для API/runtime;
  - операционные метрики API/runtime;
  - formal single-instance policy для runtime/write операций;
  - runbook (операции/инциденты/rollback);
  - smoke/integration и CI merge gate для Stage 4.
- Вне scope:
  - изменение Telegram UX/поведения;
  - новые Telegram UI сценарии;
  - Stage 5 Q/A API реализация.

## 4. Нормативные контракты Stage 4

### 4.1 Correlation ID
- `X-Correlation-Id` принимается из входящего запроса; при отсутствии генерируется.
- `X-Correlation-Id` обязателен в каждом HTTP response.
- `X-Correlation-Id` обязателен в API/application/runtime логах по пути обработки запроса.
- В error envelope обязательно: `error.details.correlation_id`.
- Сохранение correlation_id в доменные таблицы не требуется для Stage 4.

### 4.2 Метрики (обязательный минимум)
- `http_requests_total{method,route,status}`
- `http_request_duration_ms{method,route,status}`
- `runtime_operations_total{operation,result,error_code}`
- `runtime_queue_wait_ms{operation}`
- `runtime_busy_conflict_total{operation}`
- `runtime_pending_replay_total{result}`
- `runtime_inflight_operations{operation}`
- `runtime_queue_depth{queue_name}`

### 4.3 Single-instance policy
- Только runner-инстанс выполняет runtime/write операции.
- Queue in-memory и не шарится между инстансами.
- Горизонтальный scale runtime без внешнего backend запрещён.
- Non-runner для runtime/write возвращает детерминированный reject:
  - HTTP `409`;
  - machine code: `runtime_non_runner_reject`.
- Read API на non-runner доступен.
- Обязательный операторский endpoint состояния runtime:
  - `is_runner`;
  - `dispatch_mode`;
  - `queue_backend`;
  - `started_at`.

## 5. Блокирующие acceptance criteria (Stage 4 GO)

### B1. Correlation/trace сквозной контракт
- [x] В каждом HTTP response возвращается `X-Correlation-Id`.
- [x] Correlation-id сквозной в API/application/runtime логах.
- [x] Для ошибок присутствует `error.details.correlation_id`.

### B2. Метрики Runtime/API
- [x] Все обязательные метрики из раздела 4.2 эмитятся.
- [x] Метки (`labels`) соответствуют контракту.
- [x] Есть sanity-проверки/тесты на эмиссию.

### B3. Single-instance enforcement
- [x] Runtime/write операции на non-runner блокируются с `409`.
- [x] Используется machine code `runtime_non_runner_reject`.
- [x] Read API доступен на non-runner.
- [x] Реализован runtime status endpoint для операторов.

### B4. Runbook
- [x] Обновлён runbook по запуску и режимам API/runtime.
- [x] Зафиксирован мониторинг и алерты по метрикам Stage 4.
- [x] Зафиксированы инцидентные процедуры:
  - busy-stuck;
  - queue reject;
  - pending replay failure.
- [x] Зафиксирован rollback до предыдущего релиза.
- Reference runbook:
  - `docs/fastapi_migration/16_stage4_runtime_api_hardening_runbook.md`.

### B5. Smoke/integration coverage
- [x] API standalone startup smoke.
- [x] Read/write happy-path smoke.
- [x] Authz smoke (`200/401/403`).
- [x] Correlation-id propagation.
- [x] Metrics emission sanity.
- [x] Single-instance reject scenario.
- [x] Rollback drill (частичный fail + восстановление).

### B6. CI merge gate
- [x] Добавлен blocking job/script: `stage4_runtime_api_hardening_gates`.
- [x] В состав job включены:
  - Stage 2 gates;
  - Stage 3 gates;
  - Stage 4-specific tests.
- [x] Job стабильно зелёный в CI.
- CI workflow:
  - `.github/workflows/stage4_runtime_api_hardening_gates.yml`.

### B7. Sign-off
- [x] Подготовлен Stage 4 sign-off документ в `docs/fastapi_migration`.
- [x] Формат sign-off:
  - checklist;
  - итог `GO/NO-GO`;
  - дата/время;
  - ссылки на CI/job и ключевые артефакты.

## 6. CI/артефакты (для заполнения при закрытии)
- Stage 4 job:
  - CI workflow/job URL: `.github/workflows/stage4_runtime_api_hardening_gates.yml`
  - Последний зелёный run id: `local:2026-04-05T17:13:15Z`
- Stage 2 gates reference:
  - CI URL: `.github/workflows/stage2_read_api_gates.yml`
  - Script: `scripts/stage2_read_api_gates.sh`
- Stage 3 gates reference:
  - CI URL: `.github/workflows/stage3_write_api_gates.yml`
  - Script: `scripts/stage3_write_api_gates.sh`
- Stage 4 gates reference:
  - CI URL: `.github/workflows/stage4_runtime_api_hardening_gates.yml`
  - Script: `scripts/stage4_runtime_api_hardening_gates.sh`
  - Workflow: `.github/workflows/stage4_runtime_api_hardening_gates.yml`

## 7. Definition of Done (Stage 4)
- Все блокеры B1-B7 закрыты.
- `stage4_runtime_api_hardening_gates` зелёный.
- Runbook и sign-off опубликованы.
- Stage 4 status: `GO`.

Статус: **DONE (2026-04-05)**.
