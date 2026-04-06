# 14. Stage 5 Q/A API Orchestration Spec

Дата фиксации: **2026-04-05**
Статус реализации: **DONE (Stage 5 v1 GO, 2026-04-05; Dispatch Bridge v1 GO, 2026-04-06)**.

## 1. Цель
- Зафиксировать архитектуру и минимальный реализационный контракт Stage 5 для сценария "отправка вопроса / получение ответа".
- Согласовать доменную модель Q/A, статусную машину, lineage/thread модель и orchestrator feed.
- Определить rollout и блокирующие гейты для завершения этапа.
- Execution baseline/checklist:
  - `docs/fastapi_migration/18_stage5_qa_api_execution_checklist.md`.
- Операционный runbook:
  - `docs/fastapi_migration/19_stage5_qa_api_runbook.md`.
- Sign-off:
  - `docs/fastapi_migration/20_stage5_qa_api_signoff.md`.

## 2. Границы Stage 5
- В scope:
  - HTTP/API методы Q/A в `/api/v1`;
  - storage/domain/application/runtime интеграция для Q/A lifecycle;
  - idempotency и cursor-pagination для multi-client consistency;
  - orchestrator feed только в рамках своей команды.
- Вне scope:
  - изменения Telegram UX/поведения;
  - новые Telegram UI сценарии;
  - unrelated write API расширения вне Q/A lifecycle.

## 3. Доменная модель

### 3.1 Сущности
- `Question`:
  - `question_id` (global unique, UUIDv7);
  - `thread_id` (UUIDv7);
  - `team_id`;
  - `requested_by_user_id`;
  - `target_role_id` или `target_scope`;
  - `origin_type`: `user | role_dispatch | orchestrator`;
  - `source_question_id` (nullable);
  - `parent_answer_id` (nullable);
  - `status`: `accepted | queued | in_progress | answered | failed | cancelled | timeout`;
  - `error_code`/`error_message` (только terminal error);
  - `created_at`/`updated_at`/`sla_deadline_at`.
- `Answer`:
  - `answer_id` (global unique, UUIDv7);
  - `question_id`;
  - `thread_id`;
  - `team_id`;
  - `role_id`;
  - `team_role_id`;
  - `role_name`;
  - `text`;
  - `is_final`;
  - `created_at`.
- `IdempotencyRecord`:
  - `scope` (минимум `qa.create_question`);
  - `idempotency_key`;
  - `request_fingerprint`;
  - `question_id`;
  - `created_at`/`expires_at`.

### 3.2 Связи и lineage
- `Question(1) -> (0..N) Answer`.
- `Answer -> Question` (переход цепочки): новый вопрос может ссылаться на `parent_answer_id` и `source_question_id`.
- Thread собирается по `thread_id`; для v1 достаточно line-level retrieval, без graph API.

## 4. Статусная машина
- Базовый путь: `accepted -> queued -> in_progress -> answered`.
- Terminal ветки:
  - `in_progress -> failed`;
  - `in_progress -> timeout`;
  - `accepted|queued|in_progress -> cancelled`.
- Для `failed` обязательно сохранять:
  - `error_code`;
  - `error_message`.

## 5. API v1 (минимальный контракт)
- `POST /api/v1/questions`:
  - создаёт вопрос;
  - `Idempotency-Key` обязателен.
  - `team_id` обязателен;
  - `team_role_id` опционален;
  - приоритет routing: `team_role_id` > single role-tag в тексте > fallback на orchestrator команды;
  - без `team_role_id` и без tag:
    - если в `team_id` ровно один активный orchestrator-role (`is_orchestrator=true`, `is_active=true`, `enabled=true`) — routing на него;
    - выбранный orchestrator сохраняется как explicit target (`team_role_id`) в `Question`;
    - если orchestrator нет -> `422 qa_orchestrator_not_configured`;
    - если orchestrator больше одного -> `422 qa_orchestrator_ambiguous`;
  - без `team_role_id` и при `>1` тегов fallback не применяется -> `422 qa_lineage_invalid`;
  - при несовпадении `team_role_id` и `team_id`: `422 qa_lineage_invalid`;
  - `team not found` и `team_role not found`: `404 qa_not_found`;
  - legacy alias полей роли не поддерживаются (каноничное поле: `team_role_id`).
- `GET /api/v1/questions/{question_id}/status`:
  - возвращает текущий статус.
- `GET /api/v1/questions/{question_id}`:
  - возвращает запись вопроса.
- `GET /api/v1/answers/{answer_id}`:
  - возвращает запись ответа.
- `GET /api/v1/questions/{question_id}/answer`:
  - резолвит текущий/финальный ответ по вопросу.
  - при неготовом ответе: `409` + `qa_answer_not_ready`.
- `GET /api/v1/qa-journal`:
  - фильтры: `team_id`, `role_id`, `status`, `time_from`, `time_to`, `thread_id`, `orchestrator_view`;
  - cursor-pagination обязательна.
- `GET /api/v1/threads/{thread_id}`:
  - возвращает thread-линейку.
- `GET /api/v1/orchestrator/feed`:
  - отдельный feed для orchestrator;
  - в кейсе `user -> role -> orchestrator`: агрегированный пакет `question + answer` + ссылки на сущности.

## 6. Mapping на текущий runtime
- Queue:
  - используем существующий `RoleDispatchQueueService` для перехода `queued -> in_progress`.
- Runtime status:
  - используем `RoleRuntimeStatusService` как источник busy/free-транзишнов для Q/A статусов.
- Pending:
  - API не воспроизводит Telegram pending UX;
  - pending-related runtime события маппятся на Q/A error/status contract.
- Orchestrator:
  - используем текущую post-event оркестрацию как источник feed-пакетов.

## 7. Execution план по слоям и зависимостям
- `storage`:
  - миграции таблиц Q/A/idempotency/feed + индексы под фильтры/курсор.
- `domain`:
  - сущности/инварианты lineage/status machine.
- `application`:
  - use-cases create/get/status/journal/thread/feed + mapping runtime events.
- `api`:
  - DTO, роуты, owner-only authz, error envelope, OpenAPI.
- `tests`:
  - integration/e2e + contract tests для endpoint-ов;
  - инварианты status/lineage/orchestrator/idempotency/pagination.
- `ci`:
  - blocking job `stage5_qa_api_gates`.
- `docs`:
  - runbook + sign-off.

## 8. Blocking gates Stage 5
- Подтверждена тестами статус-машина Q/A.
- Подтверждены lineage/thread инварианты.
- Подтверждён orchestrator feed контракт.
- Подтверждены idempotency и cursor pagination.
- Blocking OpenAPI snapshot зелёный.
- `stage5_qa_api_gates` зелёный.
- Для execution-моста `accepted -> terminal`:
  - `stage5_execution_bridge_gates` зелёный.
- Runbook и sign-off опубликованы.

## 9. Rollout
- 5.1: schema + domain contracts (без внешнего API).
- 5.2: application use-cases и runtime mapping.
- 5.3: HTTP endpoints + DTO/OpenAPI.
- 5.4: тесты, snapshot, CI gate.
- 5.5: runbook + sign-off.
