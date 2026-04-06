# 02. Оценка готовности к FastAPI API (обновлено по текущему коду)

## 1. Цель и критерии оценки
- Цель: оценить фактическую готовность системы к завершению Stage 1 (без HTTP) и входу в Stage 2 (read-only FastAPI) по текущему коду.
- Критерии:
  - отделение application/use-case слоя от Telegram transport;
  - единая модель ошибок и бизнес-результатов;
  - транзакционная целостность и UoW-guard;
  - готовность dependency boundary для API transport;
  - наличие API-boundary DTO/схем и тестов контрактов;
  - достаточность quality gates перед стартом Stage 2.

## 2. Что уже готово (по коду)

### 2.1 Application boundary существенно усилен
- Выделены transport-независимые use-cases для группового runtime/pending/callback orchestration:
  - `app/application/use_cases/group_runtime.py:49`
  - `app/application/use_cases/group_runtime.py:152`
  - `app/application/use_cases/private_pending_field.py:15`
  - `app/application/use_cases/runtime_orchestration.py:126`
  - `app/application/use_cases/callback_role_actions.py:17`
- В handlers уже есть вызовы application use-cases вместо инлайновой доменной логики:
  - `app/handlers/messages_group.py:15`
  - `app/handlers/messages_group.py:16`
  - `app/handlers/messages_private.py:18`
  - `app/handlers/callbacks.py:18`

### 2.2 Единый error/result contract введён
- Стабильные machine-codes и маппинг в HTTP-статусы:
  - `app/application/contracts/errors.py:7`
  - `app/application/contracts/errors.py:18`
  - `app/application/contracts/errors.py:34`
- Унифицированный `Result/AppError` для application слоя:
  - `app/application/contracts/result.py:11`
  - `app/application/contracts/result.py:23`
  - `app/application/contracts/result.py:65`
- Есть transport-agnostic адаптер ошибки для API payload:
  - `app/application/contracts/error_transport.py:9`

### 2.3 Authz/policy вынесен из ad-hoc owner checks
- Базовая owner-only policy реализована как отдельный сервис:
  - `app/application/authz/policies.py:8`
  - `app/application/authz/policies.py:17`
- Интеграция policy в runtime/bootstrap:
  - `app/app_factory.py:10`
  - `app/app_factory.py:136`
  - `app/interfaces/telegram/adapter.py:154`

### 2.4 UoW и транзакционные границы заметно усилены
- В `Storage` есть явная транзакция с savepoint и runtime-guard записи вне UoW:
  - `app/storage.py:40`
  - `app/storage.py:65`
  - `app/storage.py:79`
- Guard включается на старте runtime:
  - `app/app_factory.py:183`
- Критичные команды в `core/use_cases/team_roles.py` обёрнуты `storage.transaction(immediate=True)`:
  - `app/core/use_cases/team_roles.py:86`
  - `app/core/use_cases/team_roles.py:170`
  - `app/core/use_cases/team_roles.py:257`

### 2.5 Dependency boundary для API transport подготовлен
- Runtime dependency provider типизирован и отдаёт срезы зависимостей для orchestration/queue/storage/pending/tooling/authz:
  - `app/application/dependencies/providers.py:22`
  - `app/application/dependencies/providers.py:44`
  - `app/application/dependencies/providers.py:74`
  - `app/application/dependencies/providers.py:92`
- В `app/interfaces/api/dependencies.py` есть готовый слой подключения runtime в `app_state`:
  - `app/interfaces/api/dependencies.py:29`
  - `app/interfaces/api/dependencies.py:38`
  - `app/interfaces/api/dependencies.py:59`
  - `app/interfaces/api/dependencies.py:101`
- Runtime уже экспортирует `runtime_dependencies`:
  - `app/runtime.py:88`
  - `app/runtime.py:96`
  - `app/app_factory.py:243`

### 2.6 API-boundary schemas/DTO уже есть (как pre-Stage 2 актив)
- База Pydantic-схем и request/result DTO:
  - `app/interfaces/api/schemas/common.py:8`
  - `app/interfaces/api/schemas/operations.py:13`
  - `app/interfaces/api/schemas/operations.py:51`
- Конвертеры domain->DTO и `Result`->operation DTO:
  - `app/interfaces/api/schemas/adapters.py:26`
  - `app/interfaces/api/schemas/adapters.py:70`

## 3. Ограничения и пробелы (актуальные риски)

### 3.1 Transport coupling ещё не снят полностью
- Telegram handlers всё ещё содержат orchestration glue, buffering/UX и transport-специфичные ветки:
  - `app/handlers/messages_group.py:55`
  - `app/handlers/messages_group.py:140`
  - `app/handlers/messages_private.py:232`
  - `app/handlers/commands.py:95`
- Это не блокирует Stage 1 exit, но усложняет чистую reuse-модель для будущих HTTP endpoint handlers.

### 3.2 RuntimeContext остаётся крупным агрегатом
- `RuntimeContext` содержит широкий набор зависимостей и mutable runtime state:
  - `app/runtime.py:32`
  - `app/runtime.py:50`
  - `app/runtime.py:71`
- Для Stage 2 это риск избыточной связанности endpoint dependencies.

### 3.3 Stage 2 (read-only FastAPI) реализован минимальным обязательным контуром
- Риск снят: реализован минимальный read-only FastAPI transport layer (`GET /teams`, `GET /teams/{team_id}/roles`, `GET /teams/{team_id}/runtime-status`) с owner-only authz и unified error envelope.
- Подтверждающие факты:
  - `app/interfaces/api/read_only_app.py:57`
  - `app/interfaces/api/read_only_app.py:116`
  - `app/interfaces/api/read_only_app.py:145`
  - `requirements.txt:6`
  - `requirements.txt:7`

### 3.4 Масштабирование ограничено in-memory dispatch policy
- Очередь исполнения в текущем виде зависит от процесса/инстанса (policy-mode `single-instance`/`single-runner`):
  - `app/app_factory.py:112`
  - `app/runtime.py:84`
  - `app/interfaces/api/dependencies.py:101`
- Для Stage 2 read-only это допустимо, но важно явно зафиксировать эксплуатационные ограничения.

## 4. Вывод по готовности

### 4.1 Stage 1 exit (без HTTP)
- Оценка: **9.4/10**
- Вердикт: **GO**.
- Обоснование:
  - application use-cases выделены и применяются в transport-слое;
  - unified error/result contract и authz-policy присутствуют;
  - UoW-guard и атомарность ключевых multi-step операций подтверждены тестами;
  - dependency boundary для API transport подготовлен.

### 4.2 Stage 2 start (read-only FastAPI)
- Оценка: **9.1/10**
- Вердикт: **GO**.
- Обоснование:
  - реализован HTTP transport layer для read-only Stage 2;
  - закрыты quality gates по regression/runtime, API contract/integration, owner-only authz, DTO/response shape;
  - `stage2_gates` подтверждён как зелёный без skip.

## 5. Тестовые подтверждения и gaps

### 5.1 Подтверждения (что уже покрыто)
- Application extraction/use-case behavior:
  - `tests/test_ltc42_group_runtime_use_cases.py:122`
  - `tests/test_ltc42_group_runtime_use_cases.py:168`
  - `tests/test_ltc42_private_pending_use_cases.py:126`
  - `tests/test_ltc42_callback_use_cases.py:96`
- Error model/contract:
  - `tests/test_ltc43_error_model.py:9`
  - `tests/test_ltc43_error_contracts.py:58`
  - `tests/test_ltc46_runtime_error_codes.py:9`
- UoW/atomicity:
  - `tests/test_ltc56_storage_uow_guard.py:12`
  - `tests/test_ltc56_storage_uow_guard.py:52`
  - `tests/test_ltc44_uow_atomicity.py:24`
  - `tests/test_ltc44_uow_atomicity.py:107`
- Authz/dependencies:
  - `tests/test_ltc45_authz_policy.py:17`
  - `tests/test_ltc47_dependency_providers.py:45`
  - `tests/test_ltc50_multi_instance_runtime_mode.py:98`
- Runtime transitions/observability:
  - `tests/test_ltc46_runtime_transitions_contract.py:14`
  - `tests/test_ltc49_observability_correlation_metrics.py:142`
  - `tests/test_ltc49_observability_correlation_metrics.py:210`
- API schema/DTO contracts:
  - `tests/test_ltc48_api_schema_contract.py:22`
  - `tests/test_ltc48_api_schema_dto.py:51`
  - `tests/test_ltc48_api_schema_dto.py:82`

### 5.2 Gaps после sign-off (не блокируют Stage 2)
- Блокирующих gaps для старта Stage 2 не выявлено (quality gates закрыты).
- Остаточные неблокирующие зоны:
  - расширение read-only endpoint покрытия за пределами минимального набора;
  - развитие API-level observability и расширение OpenAPI snapshot checks;
  - подготовка write API этапа (Stage 3+) с сохранением текущих UoW/authz контрактов.

## 6. Quality Gates перед Stage 2 (обязательные)
1. [x] Реализован минимальный FastAPI app factory + read routers, без write endpoints.
2. [x] Добавлены endpoint contract tests (`TestClient`) для ключевых read маршрутов и стабильных payload shape.
3. [x] Добавлены HTTP error mapping tests (`Result.error` -> JSON + status code).
4. [x] Добавлены authz dependency tests для owner-only policy в HTTP transport.
5. [x] Добавлен OpenAPI snapshot test (минимум: route list + response schemas на read endpoints).
6. [x] Зафиксирован operational constraint single-instance/single-runner в API docs и smoke checks.

## 7. Что сделано после 03 / что осталось до Stage 2

### 7.1 Уже сделано после 03
- Выделен application use-case слой и интегрирован в handlers.
- Введён unified error/result contract с HTTP-ориентированным статус-мэппингом.
- Вынесен authz policy слой (`OwnerOnlyAuthzService`).
- Усилен UoW/atomicity (write guard + транзакционные use-cases + тесты).
- Подготовлены API dependency provider и Pydantic schema boundary.

### 7.2 Осталось до Stage 2
- Stage 2 readiness-блокеры закрыты.
- Дальнейшие шаги относятся к развитию Stage 2+ (расширение read API, observability, подготовка write API).

## 9. Addendum — Stage 1 Sign-off Completed (2026-04-05)
- Статус sign-off: **завершён**.
- `Stage 1 exit`: **GO**.
- `Stage 2 start`: **GO**.
- Подтверждение качества: `scripts/stage2_gates.sh` пройден **без skip**.

## 8. Трассируемость (код/тесты)
- Application contracts/errors/results:
  - `app/application/contracts/errors.py:7`
  - `app/application/contracts/result.py:23`
  - `app/application/contracts/error_transport.py:9`
- Use-cases/runtime orchestration:
  - `app/application/use_cases/group_runtime.py:49`
  - `app/application/use_cases/runtime_orchestration.py:17`
  - `app/application/use_cases/runtime_orchestration.py:126`
- Dependencies/authz/runtime container:
  - `app/application/dependencies/providers.py:22`
  - `app/interfaces/api/dependencies.py:29`
  - `app/application/authz/policies.py:8`
  - `app/app_factory.py:136`
  - `app/app_factory.py:183`
  - `app/runtime.py:32`
- Storage/UoW:
  - `app/storage.py:40`
  - `app/storage.py:65`
  - `app/storage.py:79`
  - `app/core/use_cases/team_roles.py:86`
- API schema boundary:
  - `app/interfaces/api/schemas/common.py:8`
  - `app/interfaces/api/schemas/operations.py:13`
  - `app/interfaces/api/schemas/adapters.py:70`
- Tests:
  - `tests/test_ltc42_group_runtime_use_cases.py:122`
  - `tests/test_ltc42_private_pending_use_cases.py:126`
  - `tests/test_ltc43_error_model.py:9`
  - `tests/test_ltc43_error_contracts.py:58`
  - `tests/test_ltc44_uow_atomicity.py:24`
  - `tests/test_ltc45_authz_policy.py:17`
  - `tests/test_ltc46_runtime_transitions_contract.py:14`
  - `tests/test_ltc47_dependency_providers.py:45`
  - `tests/test_ltc48_api_schema_contract.py:22`
  - `tests/test_ltc49_observability_correlation_metrics.py:142`
  - `tests/test_ltc50_multi_instance_runtime_mode.py:98`
  - `tests/test_ltc56_storage_uow_guard.py:12`
