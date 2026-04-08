# 19. Stage 5 Q/A API Runbook

Дата фиксации: **2026-04-05**

## 1. Цель
- Описать эксплуатационный контур Stage 5 v1 для Q/A API lifecycle.
- Зафиксировать семантику статусов, lineage/thread, idempotency, cursor-pagination и orchestrator feed.
- Сохранить strict backward compatibility Telegram UX.

## 2. Endpoint scope (Stage 5 v1)
- `POST /api/v1/questions`
- `GET /api/v1/questions/{question_id}/status`
- `GET /api/v1/questions/{question_id}`
- `GET /api/v1/answers/{answer_id}`
- `GET /api/v1/questions/{question_id}/answer`
- `GET /api/v1/qa-journal`
- `GET /api/v1/threads/{thread_id}`
- `GET /api/v1/orchestrator/feed`

### 2.1 Addendum: Stage 5 API parity extension (2026-04-06, baseline)
- Новые read endpoint-ы:
  - `GET /api/v1/skills`
  - `GET /api/v1/pre_processing_tools` (legacy, заменён в Wave 2)
  - `GET /api/v1/post_processing_tools` (legacy, заменён в Wave 2)
- Новый write endpoint:
  - `PATCH /api/v1/roles/{role_id}` (master-role patch, `409` при конфликте имени).
- Изменённые endpoint-ы:
  - `GET /api/v1/teams/{team_id}/roles`:
    - добавлены `skills`, `pre_processing_tools`, `post_processing_tools` (только enabled, сортировка по `id`);
  - `GET /api/v1/roles/catalog`:
    - master-role shape: `role_id`, `role_name`, `llm_model`, `system_prompt`, `extra_instruction`, `has_errors`, `source`;
    - `include_inactive` принимался и игнорировался (compat mode, до Wave 2);
  - `GET /api/v1/qa-journal`:
    - добавлено `answer_id` (nullable).

### 2.2 Addendum: API parity extension Wave 2 (2026-04-08, current)
- Консолидирован pre/post endpoint:
  - `GET /api/v1/prepost_processing_tools`;
  - `/api/v1/pre_processing_tools` и `/api/v1/post_processing_tools` удалены из роутера/OpenAPI.
- `GET /api/v1/skills` и `GET /api/v1/prepost_processing_tools`:
  - `source` возвращается как POSIX путь относительно корня репо или `null`.
- `GET /api/v1/roles/catalog`:
  - `include_inactive` удалён из API-контракта.
- `GET /api/v1/teams/{team_id}/roles`:
  - обязательный `team_role_id`;
  - `is_active` читается из `team_roles.is_active`;
  - `include_inactive=false` -> только active;
  - `include_inactive=true` -> active + inactive.
- `GET /api/v1/teams/{team_id}/runtime-status`:
  - только active team roles;
  - стабильный порядок по `team_role_id`.
- `POST /api/v1/questions`:
  - `created_by_user_id` удалён из публичного input;
  - автор берётся из owner-only контекста;
  - legacy `created_by_user_id` в payload принимается и игнорируется.
- `GET /api/v1/questions/{question_id}` и `/status`:
  - добавлен `answer_id` (`nullable`).
- Новый endpoint:
  - `POST /api/v1/teams/{team_id}/roles/{role_id}` (идемпотентный bind, `200`/`404`).

## 3. Нормативная семантика Stage 5

### 3.1 Status machine
- Базовый путь:
  - `accepted -> queued -> in_progress -> answered`
- Terminal ветки:
  - `in_progress -> failed|cancelled|timeout`
- `GET /questions/{id}/answer`:
  - если ответ не готов: `409` + `qa_answer_not_ready`.

### 3.2 Lineage/thread
- Инварианты:
  - `question_id`, `answer_id` глобально уникальны;
  - `thread_id` обязателен для вопроса/ответа;
  - `parent_answer_id` и `source_question_id` валидируются как ссылочная lineage.
- `GET /threads/{thread_id}` возвращает cursor-страницы:
  - `questions`;
  - `answers`.

### 3.3 Idempotency (create question)
- Обязательный `Idempotency-Key` только для `POST /questions`.
- Хранилище idempotency: DB (`qa_idempotency`), не in-memory.
- Повтор с тем же ключом и тем же payload:
  - replay того же результата.
- Повтор с тем же ключом и иным payload:
  - `422` + `qa_idempotency_mismatch`.

### 3.6 Team routing (`POST /questions`)
- `team_id` обязателен.
- `team_role_id` опционален и является единственным каноничным полем явного target.
- Приоритет routing:
  - explicit `team_role_id` -> single role-tag в тексте -> fallback на orchestrator команды.
- Если переданы и `team_role_id`, и role-теги в тексте:
  - routing выполняется по `team_role_id`, теги игнорируются.
- Если `team_role_id` не передан:
  - при 1 role-теге routing выполняется по role-тегу;
  - 0 тегов -> fallback на orchestrator-role команды;
  - >1 тега -> `422 qa_lineage_invalid`.
- Fallback orchestrator:
  - критерий активного orchestrator-role: `is_orchestrator=true`, `is_active=true`, `enabled=true`;
  - ровно 1 orchestrator -> выбранный `team_role_id` сохраняется в `Question` как explicit target;
  - 0 orchestrator -> `422 qa_orchestrator_not_configured`;
  - >1 orchestrator -> `422 qa_orchestrator_ambiguous`.
- Валидации соответствия:
  - `team_role_id` не принадлежит `team_id` -> `422 qa_lineage_invalid`;
  - `team_id` not found -> `404 qa_not_found`;
  - `team_role_id` not found -> `404 qa_not_found`.

### 3.4 Cursor-pagination
- Применяется для:
  - `GET /qa-journal`;
  - `GET /orchestrator/feed`;
  - `GET /threads/{thread_id}` (по разделам `questions`/`answers`).
- Контракт:
  - `limit` default `50`, max `200`;
  - opaque cursor;
  - сортировка `created_at DESC` + стабильный tie-breaker по id.

### 3.5 Orchestrator feed
- `GET /orchestrator/feed` доступен только owner.
- Feed scope: только данные команды (`team_id`).
- Используется как read-представление событий Q/A для orchestration сценариев.

## 4. Error/status contract
- Успех:
  - `POST /questions` -> `202`;
  - read endpoint-ы -> `200`.
- Ошибки:
  - `401/403` owner-only authz;
  - `404` not found (`qa_not_found` и сопутствующие);
  - `409` conflict/not-ready (`qa_answer_not_ready`, runtime conflicts);
  - `422` validation/invariant (`qa_lineage_invalid`, `qa_orchestrator_not_configured`, `qa_orchestrator_ambiguous`, `qa_idempotency_mismatch`, invalid cursor);
  - единый error envelope + `details.correlation_id`.
- Для API parity extension:
  - `GET /skills|/prepost_processing_tools`: `200/401/403`;
  - `PATCH /roles/{role_id}`: `200/401/403/404/409/422`.
  - `POST /teams/{team_id}/roles/{role_id}`: `200/401/403/404`.

## 5. Операционные проверки

### 5.1 Минимальный smoke (ручной)
1. Поднять API standalone.
2. Создать вопрос `POST /questions` с `Idempotency-Key`.
3. Проверить `GET /questions/{id}/status` и `GET /questions/{id}`.
4. Проверить `GET /qa-journal` и `GET /threads/{thread_id}`.
5. Проверить `GET /orchestrator/feed?team_id=...`.
6. Проверить authz:
   - без owner -> `401`;
   - non-owner -> `403`.

### 5.2 CI gate
- Baseline Script/Workflow:
  - `scripts/stage5_qa_api_gates.sh`
  - `.github/workflows/stage5_qa_api_gates.yml`
- Dispatch bridge Script/Workflow:
  - `scripts/stage5_execution_bridge_gates.sh`
  - `.github/workflows/stage5_execution_bridge_gates.yml`
- Оба gate являются blocking merge criteria для Stage 5 + bridge semantics.

## 6. Инцидентные заметки
- `qa_answer_not_ready` всплеск:
  - проверить runtime queue/status и transitions;
  - проверить terminal-состояния (`timeout`, `failed`).
- `qa_idempotency_mismatch` рост:
  - проверить клиентскую дисциплину `Idempotency-Key`;
  - сверить payload fingerprint policy.
- `qa_lineage_invalid`:
  - проверить корректность parent/source references на стороне producer.

## 8. Dispatch Bridge v1 (внутреннее исполнение POST /questions)

### 8.1 Worker-модель
- `in-process background worker` в FastAPI (single-instance policy).
- Trigger:
  - event-driven enqueue после `POST /api/v1/questions`;
  - fallback polling sweep для recovery.
- Порядок/конкурентность:
  - один worker loop;
  - ограниченный параллелизм с сериализацией по `team_role_id`.

### 8.2 Retry/timeout и terminal semantics
- Attempt TTL: `120s`.
- Retry policy:
  - до `3` попыток (первичная + `2` retry).
- Lease sweep:
  - `in_progress` с истёкшим lease -> requeue (до лимита попыток);
  - по исчерпанию попыток -> terminal `timeout` (`provider_timeout`).
- Минимальные machine codes bridge:
  - `runtime_busy_conflict`
  - `provider_timeout`
  - `provider_error`
  - `dispatch_rejected`
  - `internal_execution_error`

### 8.3 Observability (минимум)
- Structured logs на ключевых переходах:
  - `qa_bridge_dispatch_started`
  - `qa_bridge_dispatch_answered`
  - `qa_bridge_dispatch_retry`
  - `qa_bridge_dispatch_failed`
  - `qa_bridge_sweep_requeued`
  - `qa_bridge_sweep_timed_out`
- Обязательные log-поля:
  - `correlation_id`, `question_id`, `team_id`, `team_role_id`, `attempt`.
- Метрики bridge:
  - `runtime_queue_depth{queue_name=qa_dispatch_bridge}`
  - `runtime_inflight_operations{operation=qa_dispatch_bridge}`
  - `runtime_transition_latency_ms{operation,status}`
  - `runtime_operations_total{operation,result,error_code}` (`started|retry|answered|failed|timeout`).

### 8.4 CI gate
- Script:
  - `scripts/stage5_execution_bridge_gates.sh`
- Workflow:
  - `.github/workflows/stage5_execution_bridge_gates.yml`
- Gate policy:
  - blocking merge gate;
  - включает baseline `stage5_qa_api_gates` + bridge-specific suites.

## 9. Связанные документы
- `docs/fastapi_migration/14_stage5_qa_api_orchestration_spec.md`
- `docs/fastapi_migration/18_stage5_qa_api_execution_checklist.md`
- `docs/fastapi_migration/26_stage5_api_parity_extension_checklist.md`
- `docs/fastapi_migration/04_migration_roadmap_and_risks.md`
