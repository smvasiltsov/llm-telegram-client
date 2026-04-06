# 20. Stage 5 v1 Q/A API Sign-off

Дата: **2026-04-05**  
Время (UTC): **2026-04-05T19:05:00Z**

Addendum (contract patch): **2026-04-06T00:00:00Z** (`team_id/team_role_id` routing fix, additive-only, без Telegram UX-регрессий).
Addendum (contract patch): **2026-04-06T01:00:00Z** (orchestrator fallback routing для `POST /questions`, additive-only, без Telegram UX-регрессий).
Addendum (dispatch bridge v1): **2026-04-06T09:00:00Z** (execution bridge, retry/timeout semantics, observability и blocking gate `stage5_execution_bridge_gates`).

## 1. Решение
- Stage 5 v1 Q/A API orchestration: **GO**.
- Обязательные merge gates:
  - **`stage5_qa_api_gates`**
  - **`stage5_execution_bridge_gates`**
- Telegram-путь: **backward compatible** (UX/поведение не изменялись).

## 2. Checklist (итог)
- B1 Endpoint scope: **DONE**.
- B2 Status machine: **DONE**.
- B3 Lineage/thread invariants: **DONE**.
- B4 Idempotency + cursor: **DONE**.
- B5 Orchestrator feed: **DONE**.
- B6 HTTP contract/authz/error envelope: **DONE**.
- B7 OpenAPI snapshot: **DONE**.
- B8 E2E smoke: **DONE**.
- B9 CI merge gate: **DONE**.
- B10 Docs/sign-off: **DONE**.
- DB1-DB6 Dispatch Bridge v1 checklist: **DONE**.

Источник checklist:
- `docs/fastapi_migration/18_stage5_qa_api_execution_checklist.md`

## 3. Что сделано (DONE)
- Реализован полный Stage 5 endpoint scope в `/api/v1`:
  - create/status/get/resolve/journal/thread/orchestrator-feed.
- Зафиксирована и покрыта тестами status machine:
  - `accepted -> queued -> in_progress -> answered|failed|cancelled|timeout`.
- Внедрены обязательные machine codes Stage 5:
  - `qa_not_found`, `qa_answer_not_ready`, `qa_timeout`, `qa_lineage_invalid`, `qa_idempotency_mismatch`.
- Добавлены и покрыты тестами machine codes fallback-маршрутизации:
  - `qa_orchestrator_not_configured`, `qa_orchestrator_ambiguous`.
- Уточнён и стабилизирован контракт `POST /api/v1/questions`:
  - `team_id` strict-required;
  - `team_role_id` optional и каноничный;
  - приоритет routing: explicit `team_role_id` -> single role-tag -> fallback на orchestrator команды;
  - без `team_role_id` и без tag: fallback на единственный активный orchestrator с сохранением `Question.team_role_id`;
  - без `team_role_id` и без tag при `0 orchestrator` -> `422 qa_orchestrator_not_configured`;
  - без `team_role_id` и без tag при `>1 orchestrator` -> `422 qa_orchestrator_ambiguous`;
  - без `team_role_id` и с `>1` тегов -> `422 qa_lineage_invalid`;
  - `team_role_id` вне `team_id` -> `422 qa_lineage_invalid`;
  - `team`/`team_role` not found -> `404 qa_not_found`.
- Реализована DB idempotency для `POST /questions` (`qa_idempotency`).
- Реализованы lineage/thread инварианты и cursor contract:
  - `limit=50` default, `max=200`, opaque cursor, `created_at DESC + stable tie-breaker`.
- Реализован orchestrator feed read-model.
- Подключён blocking CI gate Stage 5:
  - `scripts/stage5_qa_api_gates.sh`
  - `.github/workflows/stage5_qa_api_gates.yml`
- Обновлён OpenAPI snapshot как blocking gate.

## 4. Что вне scope
- Новые Telegram UI фичи/изменения UX.
- Расширения write API вне Q/A lifecycle.
- Async queue API/`202+callback` beyond текущего scope.
- Расширенная модель авторизации beyond owner-only.

## 5. Остаточные риски
- Высокая зависимость от runtime очереди и статусов при всплесках нагрузки:
  - рост `qa_answer_not_ready` может требовать операционной настройки queue/runtime.
- Качество внешних producer-событий:
  - некорректные parent/source references приводят к `qa_lineage_invalid`.
- Клиентская дисциплина idempotency:
  - reuse ключа с другим payload детерминированно возвращает `qa_idempotency_mismatch`.

## 6. CI/job и артефакты
- Stage 5 gate:
  - Workflow: `.github/workflows/stage5_qa_api_gates.yml`
  - Script: `scripts/stage5_qa_api_gates.sh`
  - Локальный прогон: **PASS** (`2026-04-06`, после contract patch `team_id/team_role_id` + orchestrator fallback).
- Stage 5 ключевые test suites:
  - `tests/test_ltc76_stage5_storage_foundation.py`
  - `tests/test_ltc77_stage5_qa_use_cases.py`
  - `tests/test_ltc78_stage5_fastapi_contract.py`
  - `tests/test_ltc79_stage5_api_e2e_smoke.py`
  - `tests/test_ltc70_openapi_snapshot.py`

## 7. Консистентность Stage 2/3/4/5
- Stage 2:
  - read-only foundation и контракты сохранены;
  - Stage 5 использует Stage 2 baseline без breaking-изменений.
- Stage 3:
  - write/admin контракты не изменены;
  - Stage 5 добавляет отдельный Q/A lifecycle surface additive-only.
- Stage 4:
  - observability/single-instance/runtime-hardening baseline сохраняется и используется.
- Stage 5:
  - закрыт как отдельный orchestration milestone; readiness для следующего roadmap-этапа подтверждена.

## 8. GO/NO-GO
- Итог: **GO**.
- Разрешение на переход: **следующий этап roadmap может стартовать**.

## 9. Addendum (2026-04-06, orchestrator fallback)
- Что изменено:
  - `POST /api/v1/questions` поддерживает fallback без `team_role_id` и без tag при ровно одном активном orchestrator-role;
  - добавлены machine codes: `qa_orchestrator_not_configured`, `qa_orchestrator_ambiguous`;
  - обновлены use-case/API-contract/e2e тесты и Stage 5 docs (`14/18/19/20`).
- Риски:
  - неправильная конфигурация orchestrator в команде даёт deterministic `422`, что требует операционной настройки ролей;
  - сценарий `>1 orchestrator` остаётся защитным (ambiguous), без fan-out в v1.
- Итоговый статус:
  - additive-only patch применён без Telegram UX-регрессий;
  - `stage5_qa_api_gates` — **PASS**;
  - Stage 5 v1 статус остаётся **GO**.

## 10. Addendum (2026-04-06, dispatch bridge v1)
- Что изменено:
  - реализован `in-process` dispatch bridge для вопросов из `POST /api/v1/questions`;
  - обеспечены переходы `accepted -> queued -> in_progress -> answered|failed|timeout`;
  - добавлены deterministic retry/lease-timeout semantics (`TTL=120s`, до `3` попыток);
  - сохранение terminal результата с `answer`/`orchestrator_feed` зафиксировано как обязательный контракт;
  - добавлены structured logs (`correlation_id`, `question_id`, `team_id`, `team_role_id`, `attempt`) и bridge-метрики;
  - введён blocking gate `stage5_execution_bridge_gates` (включает baseline `stage5_qa_api_gates`).
- Риски:
  - single-instance in-process worker остаётся ограничением по масштабированию;
  - при недоступности provider ожидаем controlled рост `retry/timeout`, требует операционного мониторинга.
- Артефакты:
  - Script: `scripts/stage5_execution_bridge_gates.sh`;
  - Workflow: `.github/workflows/stage5_execution_bridge_gates.yml`;
  - Suites: `tests/test_ltc80_stage5_dispatch_bridge_foundation.py`, `tests/test_ltc81_stage5_dispatch_bridge_worker.py`, `tests/test_ltc82_stage5_execution_bridge_e2e_smoke.py`.
- Итоговый статус:
  - dispatch bridge v1 — **GO**;
  - `stage5_execution_bridge_gates` — **PASS**;
  - общий Stage 5 статус остаётся **GO**.
