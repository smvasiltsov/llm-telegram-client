# 04. План внедрения и риски

## 1. Цель документа
- Зафиксировать реалистичный поэтапный план внедрения FastAPI API поверх текущей системы без изменения действующей runtime-семантики (pending/FIFO/busy/replay).
- Определить гейты качества и риски, которые должны быть закрыты до перехода к следующему этапу.

## 2. Принципы внедрения
- FastAPI добавляется как новый interface adapter, без отключения Telegram-пути.
- Поведенческий baseline рантайма обязателен перед каждым write-этапом API.
- Составные доменные операции переводятся в application-layer use-cases до публикации write endpoint-ов.
- Любые изменения, влияющие на queue/pending, сопровождаются целевыми регрессионными тестами.

## 3. Пошаговый roadmap

### Этап 1. Application boundary stabilization (без HTTP)
- Цель:
  - отделить доменные операции от Telegram-specific кода и стабилизировать use-case слой.
- Работы:
  - вынести операции из `handlers/*` в application services/use-cases;
  - унифицировать доменные ошибки и формат бизнес-результатов;
  - определить транзакционные границы для multi-step операций.
- Артефакты:
  - application services для teams/team_roles/sessions/skills/prepost/runtime;
  - единый error mapping на уровне application слоя;
  - документированные transaction boundaries.
- Гейт перехода:
  - базовые операции вызываются без `Update/ContextTypes`;
  - ключевые runtime-тесты зелёные.

### Этап 2. FastAPI foundation (read-only)
- Цель:
  - поднять FastAPI-каркас с безопасным read-only API.
- Работы:
  - реализовать структуру `routers/services/schemas/dependencies`;
  - добавить owner-only authz dependency;
  - открыть read endpoint-ы по core сущностям (teams, team_roles, runtime status, sessions).
- Артефакты:
  - FastAPI app factory и набор read routers;
  - OpenAPI схема;
  - API contract tests для read маршрутов.
- Гейт перехода:
  - read API стабилен, backward compatibility с Telegram подтверждена.

### Этап 3. Write API для админ-операций
- Цель:
  - добавить изменяющие API-операции без изменения существующей runtime семантики.
- Работы:
  - PATCH/PUT/POST операции для team-role overrides, skills/prepost, reset session, role bindings;
  - зафиксировать idempotency и conflict behavior;
  - ввести консистентный HTTP error contract.
- Артефакты:
  - write routers + DTO schemas;
  - documented idempotency rules;
  - расширенные integration/contract tests.
- Гейт перехода:
  - write API работает на целевых сценариях;
  - baseline тесты рантайма и командных use-cases зелёные.

### Этап 4. Runtime/API hardening
- Цель:
  - довести API и runtime до эксплуатационной устойчивости.
- Работы:
  - добавить correlation/trace и операционные метрики;
  - формализовать ограничения in-memory queue (single-instance policy);
  - подготовить runbook (операции, инциденты, rollback).
- Артефакты:
  - метрики и унифицированные runtime/API логи;
  - эксплуатационный регламент;
  - smoke/integration сценарии для прод-готовности.
- Гейт завершения:
  - наблюдаемость и инцидентный контур готовы;
  - риски высокого приоритета закрыты или приняты с mitigation.
- Статус:
  - **DONE (2026-04-05, GO)**;
  - sign-off: `docs/fastapi_migration/17_stage4_runtime_api_hardening_signoff.md`;
  - checklist/runbook: `docs/fastapi_migration/15_stage4_runtime_api_hardening_checklist.md`, `docs/fastapi_migration/16_stage4_runtime_api_hardening_runbook.md`.

### Stage 5. Q/A API Orchestration (Question-Answer Lifecycle)
- Цель:
  - реализовать API-сценарий "отправка вопроса / получение ответа" с разделением create/status/get/journal;
  - ввести доменную Q/A модель со статусами, thread/lineage и orchestrator feed;
  - интегрировать Q/A lifecycle с текущим runtime (queue/status/pending mapping) без изменения Telegram UX.
- Scope:
  - HTTP/API + storage/domain/application/runtime integration для Q/A;
  - additive-only в `/api/v1`;
  - strict backward compatibility для Telegram-пути.
- Out of scope:
  - новые Telegram UI сценарии;
  - unrelated write-расширения вне Q/A lifecycle.
- Детальная спецификация:
  - `docs/fastapi_migration/14_stage5_qa_api_orchestration_spec.md`.
- Execution baseline/checklist:
  - `docs/fastapi_migration/18_stage5_qa_api_execution_checklist.md`.
- Статус:
  - **DONE (2026-04-05, GO)**;
  - runbook: `docs/fastapi_migration/19_stage5_qa_api_runbook.md`;
  - sign-off: `docs/fastapi_migration/20_stage5_qa_api_signoff.md`.
  - blocking CI gate: `scripts/stage5_qa_api_gates.sh`, `.github/workflows/stage5_qa_api_gates.yml`.

#### 5.1 Storage и schema
- Работы:
  - миграции для сущностей вопроса/ответа, thread/lineage, idempotency и feed-проекций;
  - индексы для cursor-pagination и фильтров журнала.
- Артефакты:
  - schema migration (blocking);
  - инварианты хранения (question_id/answer_id/thread_id, parent/source linkage).
- Зависимости:
  - до запуска application-layer use-cases.

#### 5.2 Domain/Application слой
- Работы:
  - use-cases: create question, get status, get question, get answer, resolve answer by question, journal/thread, orchestrator feed;
  - статус-машина (`accepted/queued/in_progress/answered/failed/cancelled/timeout`);
  - mapping runtime-state -> Q/A status и terminal error model.
- Артефакты:
  - application contracts + error mapping (blocking);
  - documented idempotency semantics (create question) и cursor semantics.
- Зависимости:
  - требует готовой schema из 5.1;
  - является базой для HTTP/DTO слоя.

#### 5.3 HTTP API (`/api/v1`)
- Работы:
  - endpoint-ы create/status/get/journal/thread/feed согласно Stage 5 spec;
  - owner-only authz, единый error envelope, correlation-id propagation;
  - cursor-pagination для журнала и feed.
- Артефакты:
  - DTO/OpenAPI контракты (blocking);
  - endpoint-level contract mapping для кодов ошибок.
- Зависимости:
  - после стабилизации domain/application из 5.2.

#### 5.4 Тесты и CI-гейты
- Работы:
  - integration/e2e покрытие Q/A lifecycle;
  - проверки status-machine, lineage/thread, orchestrator feed, idempotency, cursor pagination;
  - blocking OpenAPI snapshot.
- Артефакты:
  - обязательный CI job/script: `stage5_qa_api_gates` (blocking);
  - протокол прохождения гейтов для sign-off.
- Зависимости:
  - после готовности API и DTO из 5.3.

#### 5.5 Документация и закрытие этапа
- Работы:
  - runbook отдельного запуска/проверки Q/A API;
  - sign-off документ Stage 5 (done/out-of-scope/risks).
- Артефакты:
  - runbook (blocking);
  - sign-off документ (blocking).
- Зависимости:
  - после зелёного `stage5_qa_api_gates`.

## 4. Risk matrix

### R1. Регрессия pending/FIFO/busy
- Вероятность: высокая.
- Impact: высокий.
- Подтверждение в коде:
  - `app/services/role_pipeline.py`
  - `app/services/role_runtime_status.py`
  - `app/services/role_dispatch_queue.py`
- Mitigation:
  - baseline регрессий обязателен перед и после каждого write-релиза API;
  - изоляция runtime-изменений от transport-кода.

### R2. Частичная запись в multi-step операциях
- Вероятность: средняя/высокая.
- Impact: высокий.
- Подтверждение в коде:
  - `app/core/use_cases/team_roles.py`
  - `app/storage.py`
- Mitigation:
  - application-level unit-of-work и явные rollback policy;
  - idempotency ключи для критичных write-команд.

### R3. Несовместимость авторизации Telegram/API
- Вероятность: средняя.
- Impact: высокий.
- Подтверждение в коде:
  - `app/handlers/commands.py`
  - `app/handlers/callbacks.py`
  - `app/interfaces/telegram/adapter.py`
- Mitigation:
  - вынести policy layer и использовать единый authz dependency в API.

### R4. Ограничение масштабирования из-за in-memory queue
- Вероятность: средняя.
- Impact: средний/высокий.
- Подтверждение в коде:
  - `app/services/role_dispatch_queue.py`
  - `app/app_factory.py`
- Mitigation:
  - зафиксировать single-runtime constraint в первой версии API;
  - подготовить план выноса queue-state во внешний backend как отдельный этап.

### R5. Нестабильные API контракты ошибок
- Вероятность: средняя.
- Impact: средний.
- Подтверждение в коде:
  - `app/storage.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/commands.py`
- Mitigation:
  - единая taxonomy ошибок и централизованный exception mapper для FastAPI.

### R6. Неконсистентный Q/A lineage (thread/source/parent)
- Вероятность: средняя.
- Impact: высокий.
- Подтверждение в коде:
  - `app/services/role_pipeline.py`
  - `app/application/use_cases/runtime_orchestration.py`
- Mitigation:
  - обязательные инварианты lineage на уровне storage/domain;
  - integration tests на цепочки `answer -> next question` и thread-retrieval.

### R7. Рассинхронизация runtime состояния и Q/A статусов
- Вероятность: средняя.
- Impact: высокий.
- Подтверждение в коде:
  - `app/services/role_runtime_status.py`
  - `app/services/role_dispatch_queue.py`
  - `app/application/contracts/runtime_ops.py`
- Mitigation:
  - явный mapping runtime transitions -> Q/A status machine;
  - контрактные тесты terminal-state (`failed/cancelled/timeout`).

### R8. Неоднозначное API-представление pending-поведения
- Вероятность: средняя.
- Impact: средний/высокий.
- Подтверждение в коде:
  - `app/pending_store.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/messages_group.py`
- Mitigation:
  - API-контракт не копирует Telegram UX pending-flow напрямую;
  - унифицированная terminal/error модель для HTTP клиентов.

### R9. Непредсказуемость orchestrator feed под нагрузкой
- Вероятность: средняя.
- Impact: средний/высокий.
- Подтверждение в коде:
  - `app/services/role_pipeline.py`
  - `app/services/orchestrator_response.py`
  - `app/storage.py`
- Mitigation:
  - feed как отдельная read-модель с cursor-pagination;
  - отдельные contract/integration тесты для пакета `user -> role -> orchestrator`.

### R10. Нарушение multi-client consistency без строгой идемпотентности
- Вероятность: средняя.
- Impact: высокий.
- Подтверждение в коде:
  - `app/application/use_cases/write_api.py`
  - `app/interfaces/api/routers/read_only_v1.py`
- Mitigation:
  - обязательный `Idempotency-Key` для create-question;
  - проверки payload-fingerprint и стабильный replay-result.

## 5. Контрольные проверки на этапах
- Перед Этапом 2:
  - доменные операции доступны через application services без Telegram-context.
- Перед Этапом 3:
  - read API стабилен, authz dependency валиден, OpenAPI согласован.
- Перед Этапом 4:
  - write API покрыт contract/integration тестами;
  - критичные runtime regression tests зелёные.
- Перед Stage 5:
  - Stage 4 стабилизация завершена;
  - единый authz/error envelope/correlation baseline уже закреплён.
- Гейт завершения Stage 5:
  - статус-машина Q/A подтверждена тестами;
  - lineage/thread инварианты подтверждены тестами;
  - orchestrator feed контракт подтверждён;
  - idempotency + cursor pagination подтверждены;
  - blocking OpenAPI snapshot зелёный;
  - `stage5_qa_api_gates` зелёный;
  - runbook и sign-off документ опубликованы.
- Перед release:
  - runbook готов;
  - приняты/закрыты высокие риски;
  - подтверждена обратная совместимость Telegram-путей.

## 6. Трассируемость (код и тесты)
- Домен/хранилище:
  - `app/storage.py`
  - `app/models.py`
- Runtime orchestration:
  - `app/services/role_pipeline.py`
  - `app/services/role_runtime_status.py`
  - `app/services/role_dispatch_queue.py`
- Use-cases:
  - `app/core/use_cases/team_roles.py`
  - `app/core/use_cases/master_roles.py`
- Интерфейсный слой:
  - `app/handlers/*`
  - `app/interfaces/telegram/adapter.py`
- Базовый regression набор:
  - `tests/test_ltc13_inheritance_override.py`
  - `tests/test_ltc18_pipeline_busy_semantics.py`
  - `tests/test_core_team_roles_use_cases.py`
  - `tests/test_root_dir_pending_flow.py`
- Stage 5 reference:
  - `docs/fastapi_migration/14_stage5_qa_api_orchestration_spec.md`
