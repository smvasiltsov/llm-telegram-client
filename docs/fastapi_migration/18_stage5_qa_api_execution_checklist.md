# 18. Stage 5 v1 Q/A API Execution Checklist

Дата фиксации baseline: **2026-04-05**

## 1. Цель
- Зафиксировать baseline первой поставки Stage 5 v1.
- Закрепить blocking acceptance criteria для статуса `Stage 5 v1 = GO`.
- Синхронизировать execution-рамки с roadmap (`04`) и архитектурной спецификацией (`14`).

## 2. Baseline (на входе Stage 5)
- Stage 2: **GO**.
- Stage 3: **GO**.
- Stage 4: **DONE (GO)**.
- Источники:
  - `docs/fastapi_migration/04_migration_roadmap_and_risks.md`
  - `docs/fastapi_migration/14_stage5_qa_api_orchestration_spec.md`

## 3. Scope Stage 5 v1 (обязательный endpoint set)
- `POST /api/v1/questions`
- `GET /api/v1/questions/{question_id}/status`
- `GET /api/v1/questions/{question_id}`
- `GET /api/v1/answers/{answer_id}`
- `GET /api/v1/questions/{question_id}/answer`
- `GET /api/v1/qa-journal`
- `GET /api/v1/threads/{thread_id}`
- `GET /api/v1/orchestrator/feed`

## 4. Нормативные контракты Stage 5 v1

### 4.1 Status machine
- Полный набор статусов:
  - `accepted -> queued -> in_progress -> answered|failed|cancelled|timeout`
- Все terminal-ветки обязательны в v1.

### 4.2 HTTP/status contract
- `POST /api/v1/questions` -> `202`.
- `GET /api/v1/questions/{question_id}/answer` при неготовом ответе:
  - `409` + machine code `qa_answer_not_ready`.
- Общий контракт:
  - `422` validation/invariant;
  - `409` conflict/runtime busy/state conflict;
  - `404` not found;
  - `401/403` authz.

### 4.2.1 Contract patch: team routing (2026-04-06)
- `POST /api/v1/questions`:
  - `team_id` — **обязательное** поле;
  - `team_role_id` — **опциональное** поле;
  - альтернативные имена поля роли не поддерживаются.
- При одновременном наличии `team_role_id` и тегов роли в тексте:
  - приоритет маршрутизации у `team_role_id`;
  - теги игнорируются для routing.
- Если `team_role_id` не передан:
  - маршрутизация по single-tag роли в тексте или по fallback-правилу раздела 4.2.2;
  - 0 тегов -> применяется fallback orchestrator (раздел 4.2.2);
  - >1 тега -> `422` (валидация, fan-out вне scope v1).
- Проверка согласованности `team_role_id` и `team_id` обязательна:
  - role-not-in-team -> `422` (domain validation).
- Not found mapping:
  - team not found -> `404 qa_not_found`;
  - team_role not found -> `404 qa_not_found`.
- Backward compatibility для `POST /questions`:
  - `team_id` strict-required сразу;
  - отсутствие `team_id` -> `422`;
  - grace period не используется.
- `dispatch_mode` в payload не добавляется:
  - поведение остаётся implicit: explicit target через `team_role_id`, иначе tag-based dispatch.

### 4.2.2 Contract patch: orchestrator fallback routing (2026-04-06)
- Порядок routing для `POST /api/v1/questions`:
  - `team_role_id` (explicit target) -> single-tag routing -> fallback на orchestrator команды.
- Если переданы `team_role_id` и теги:
  - routing выполняется строго по `team_role_id`, теги игнорируются.
- Если `team_role_id` не передан и тегов несколько:
  - fallback не применяется; ответ `422` (валидация).
- Если `team_role_id` не передан и тегов нет:
  - при наличии ровно одного активного orchestrator-role в `team_id` выполняется fallback routing на него;
  - выбранный orchestrator сохраняется в `Question.team_role_id` (explicit target для трассируемости);
  - если активного orchestrator нет -> `422 qa_orchestrator_not_configured`;
  - если активных orchestrator больше одного -> `422 qa_orchestrator_ambiguous`.
- Критерий "активный orchestrator-role":
  - `is_orchestrator=true`, `is_active=true`, `enabled=true`.
- Backward compatibility:
  - изменение только в Stage 5 API логике, без изменений Telegram UX/поведения.

### 4.3 Error taxonomy (additive-only)
- Единый error envelope сохраняется.
- Обязательные Stage 5 machine codes:
  - `qa_not_found`
  - `qa_answer_not_ready`
  - `qa_timeout`
  - `qa_lineage_invalid`
  - `qa_idempotency_mismatch`
  - `qa_orchestrator_not_configured`
  - `qa_orchestrator_ambiguous`

### 4.4 Idempotency
- `Idempotency-Key` обязателен только для `POST /api/v1/questions`.
- Хранение idempotency — персистентное (DB), не in-memory.
- Payload mismatch:
  - `422` + `qa_idempotency_mismatch`.

### 4.5 Cursor pagination
- Единый opaque cursor для:
  - `GET /api/v1/qa-journal`
  - `GET /api/v1/orchestrator/feed`
- `limit`:
  - default `50`
  - max `200`
- Сортировка:
  - `created_at DESC`
  - stable tie-breaker по id.

### 4.6 Authz
- Owner-only для всех Stage 5 endpoint-ов, включая `orchestrator/feed`.

### 4.7 Transaction boundaries (обязательные)
- create question + idempotency record.
- status transitions.
- answer persist + lineage linkage.
- orchestrator feed materialization.
- Все операции выполняются в явных UoW-границах.

### 4.8 Runtime/pending mapping
- API v1 не воспроизводит Telegram pending UX.
- pending/runtime состояния маппятся в status/error contract API.

## 5. Blocking acceptance criteria (Stage 5 v1 GO)

### B1. Endpoint scope
- [x] Реализованы все endpoint-ы из раздела 3.

### B2. Статус-машина
- [x] Подтверждён полный статусный граф и terminal-ветки.

### B3. Lineage/thread invariants
- [x] Подтверждены инварианты `thread_id`, `parent_answer_id`, `source_question_id`.
- [x] Подтверждена консистентность thread retrieval.

### B4. Idempotency + cursor
- [x] DB idempotency для `POST /questions` реализована и покрыта тестами.
- [x] Opaque cursor и порядок сортировки подтверждены тестами.

### B5. Orchestrator feed
- [x] Контракт `GET /orchestrator/feed` подтверждён интеграционными тестами.

### B6. HTTP contract / authz / error envelope
- [x] Контракт статусов и machine codes подтверждён.
- [x] Owner-only authz (`200/401/403`) подтверждён.
- [x] Единый error envelope подтверждён для всех endpoint-ов.
- [x] Contract patch `team_id/team_role_id` (раздел 4.2.1) реализован и покрыт тестами.
- [x] Contract patch orchestrator fallback routing (раздел 4.2.2) реализован и покрыт тестами.

### B7. OpenAPI snapshot
- [x] OpenAPI snapshot обновлён и блокирующий.

### B8. E2E smoke
- [x] Пройден e2e smoke на поднятие app/runtime и базовый Q/A flow.

### B9. CI merge gate
- [x] Добавлен blocking job/script `stage5_qa_api_gates`.
- [x] Job стабильно зелёный.

### B10. Docs/sign-off
- [x] Обновлён Stage 5 runbook.
- [x] Подготовлен Stage 5 sign-off (checklist + GO/NO-GO + дата/время + ссылки на CI/artifacts).

## 6. Definition of Done (Stage 5 v1)
- Все блокеры B1-B10 закрыты.
- `stage5_qa_api_gates` зелёный.
- Telegram UX без регрессий.
- Stage 5 v1 status: `GO`.

## 7. Dispatch Bridge v1 (baseline 2026-04-06)

### 7.1 Scope и execution model
- Scope v1:
  - только вопросы, созданные через `POST /api/v1/questions`.
- Worker model:
  - `in-process background worker` внутри FastAPI;
  - single-instance policy.
- Trigger model:
  - event-driven enqueue при создании question;
  - fallback polling sweep для recovery.
- Concurrency:
  - один worker loop;
  - ограниченный параллелизм по `team_role_id` с сохранением порядка в пределах роли.

### 7.2 Обязательные транзакционные границы
- claim:
  - `accepted -> queued`.
- start:
  - `queued -> in_progress`.
- terminal:
  - terminal transition + persist `answer`/`orchestrator_feed` атомарно, где возможно.

### 7.3 Retry/timeout policy
- Retry:
  - max `2` retry после первичной попытки (итого до `3` execution attempts).
- Lease timeout/requeue:
  - для `in_progress` использовать lease timeout и requeue до исчерпания попыток.
- Attempt TTL/SLA:
  - `120` секунд на attempt;
  - timeout/lease sweep выполняет worker.

### 7.4 Error/status mapping (minimum)
- Terminal статус при ошибке:
  - `failed` + machine code.
- Минимальный набор machine codes:
  - `runtime_busy_conflict`
  - `provider_timeout`
  - `provider_error`
  - `dispatch_rejected`
  - `internal_execution_error`

### 7.5 Execution/persistence contracts
- Execution path:
  - использовать существующий runtime pipeline (`run_chain` / `execute_role_request`) без нового executor в v1.
- Persistence:
  - bridge обязан сохранять `answers` и `orchestrator_feed` по текущему Stage 5 контракту.
- Authz boundary:
  - owner-only только на API входе;
  - worker выполняется как trusted internal execution.

### 7.6 Observability minimum
- Structured logs:
  - обязательные поля: `correlation_id`, `question_id`, `team_id`, `team_role_id`, `attempt`.
- Метрики:
  - queue depth;
  - in_progress count;
  - transition latency;
  - retries;
  - terminal counts by `status`/`code`.

### 7.7 Blocking gate для bridge v1
- Новый blocking job/script:
  - `stage5_execution_bridge_gates`.
- Состав:
  - включает `stage5_qa_api_gates` как baseline;
  - bridge-specific integration/e2e и retry/timeout coverage.

## 8. Blocking acceptance criteria (Dispatch Bridge v1 GO)

### DB1. Status progression
- [x] `accepted` стабильно продвигается до terminal-статуса.

### DB2. Retry/timeout semantics
- [x] deterministic retry/lease-timeout/requeue semantics реализованы и покрыты тестами.

### DB3. Runtime integration
- [x] bridge использует существующий runtime pipeline без UX-регрессий Telegram.

### DB4. Persistence contract
- [x] `answers` и `orchestrator_feed` сохраняются в соответствии с текущим Stage 5 контрактом.

### DB5. Observability
- [x] обязательные structured logs и метрики bridge присутствуют и проверены.

### DB6. CI merge gate
- [x] `stage5_execution_bridge_gates` добавлен как blocking и стабильно зелёный.

## 9. Definition of Done (Dispatch Bridge v1)
- Все блокеры `DB1-DB6` закрыты.
- `stage5_execution_bridge_gates` зелёный.
- Telegram UX без регрессий.
- Dispatch Bridge v1 status: `GO`.

## 10. Артефакты закрытия Dispatch Bridge v1 (2026-04-06)
- Script gate:
  - `scripts/stage5_execution_bridge_gates.sh`
- CI workflow:
  - `.github/workflows/stage5_execution_bridge_gates.yml`
- Bridge-specific tests:
  - `tests/test_ltc80_stage5_dispatch_bridge_foundation.py`
  - `tests/test_ltc81_stage5_dispatch_bridge_worker.py`
  - `tests/test_ltc82_stage5_execution_bridge_e2e_smoke.py`
