# 26. Stage 5 API Parity Extension Checklist (Telegram UI parity)

## Статус
- Текущий этап: `Wave 2 closeout`.
- Реализация Wave 2: `DONE`.
- Контекст:
  - Stage5/bridge baseline: `GO`.
  - Данная поставка — дополнительный пакет API-доработок без изменения Telegram UX.

## Scope (Wave 2, подтверждено)
- `GET /api/v1/skills`:
  - `source` = POSIX-путь относительно корня репо;
  - если файловый источник не определён: `source = null`.
- Pre/Post endpoint consolidation:
  - целевой endpoint: `GET /api/v1/prepost_processing_tools`;
  - удалить из роутера/OpenAPI:
    - `GET /api/v1/pre_processing_tools`
    - `GET /api/v1/post_processing_tools`
  - `source` для prepost: POSIX-путь относительно корня репо, иначе `null`.
- `GET /api/v1/roles/catalog`:
  - удалить `include_inactive` из API-контракта и документации;
  - неизвестные query-параметры обрабатываются стандартным FastAPI-поведением.
- `GET /api/v1/teams/{team_id}/roles`:
  - добавить обязательный `team_role_id` в response;
  - `is_active` брать из team-binding (`team_roles.is_active`);
  - `include_inactive=false` -> только активные;
  - `include_inactive=true` -> активные + неактивные с корректным `is_active`.
- `GET /api/v1/teams/{team_id}/runtime-status`:
  - возвращать только активные team-roles;
  - порядок ответа: стабильный, по `team_role_id`.
- `POST /api/v1/questions`:
  - убрать `created_by_user_id` из публичного input/OpenAPI;
  - внутри использовать `owner_user_id` из owner-only контекста;
  - если поле `created_by_user_id` прислано клиентом: принять и игнорировать.
- `GET /api/v1/questions/{question_id}/status` и `GET /api/v1/questions/{question_id}`:
  - добавить `answer_id` (nullable);
  - для не-`answered`: `null`;
  - для `answered`: последний `answer_id` по текущей policy.
- Новый endpoint привязки master-role к команде:
  - `POST /api/v1/teams/{team_id}/roles/{role_id}`;
  - успех: `200` + DTO team-role binding;
  - повторная привязка: идемпотентный `200` с текущим состоянием;
  - `404` для team/role not found.

## Endpoint contracts (Wave 2)

### 1) `GET /api/v1/skills`
- Item shape: `skill_id`, `name`, `description`, `source`.
- `source`: POSIX-relative path от корня репо, иначе `null`.

### 2) `GET /api/v1/prepost_processing_tools`
- Item shape: `tool_id`, `name`, `description`, `source`.
- `source`: POSIX-relative path от корня репо, иначе `null`.
- Legacy endpoints `/pre_processing_tools` и `/post_processing_tools` выводятся из контракта.

### 3) `GET /api/v1/teams/{team_id}/roles`
- Обязательные поля:
  - `team_role_id`
  - `is_active` (из `team_roles.is_active`).
- `include_inactive=false`: только активные bindings.
- `include_inactive=true`: активные + неактивные bindings.
- Для вложенных `skills/pre_processing_tools/post_processing_tools`:
  - только enabled элементы;
  - сортировка по `id`.

### 4) `GET /api/v1/roles/catalog`
- Только master roles.
- Query `include_inactive` удалён из контракта.

### 5) `POST /api/v1/questions`
- Публичный input не содержит `created_by_user_id`.
- Источник автора: owner-only контекст (`owner_user_id`).
- Legacy field `created_by_user_id` в payload принимается и игнорируется.

### 6) `GET /api/v1/questions/{question_id}` и `/status`
- Добавляется `answer_id: string | null`.

### 7) `POST /api/v1/teams/{team_id}/roles/{role_id}`
- Идемпотентная bind-операция master-role -> team.
- `200` success (включая повторную привязку), `404` not found.

## Status/Code policy
- `GET /skills`, `GET /prepost_processing_tools`: `200/401/403`.
- `POST /teams/{team_id}/roles/{role_id}`: `200/401/403/404`.
- Для изменённых endpoint-ов сохраняется owner-only/authz и единый error envelope.

## Invariants
- `owner-only/authz`: без изменений.
- `additive/safe` где возможно; контрактные корректировки выполняются по согласованному scope.
- Без регрессий Stage 5/dispatch bridge.
- Telegram UX/поведение: без изменений.

## CI/Gates policy
- Blocking:
  - `scripts/stage5_qa_api_gates.sh`
  - `scripts/stage5_execution_bridge_gates.sh` (при затрагивании bridge/runtime совместимости)
- OpenAPI snapshot: blocking.

## Тестовые критерии (Wave 2, must-pass)
- Контракт/интеграция:
  - новый `GET /prepost_processing_tools`;
  - отсутствие старых `/pre_processing_tools` и `/post_processing_tools`;
  - `roles/catalog` без документированного `include_inactive`;
  - `team_role_id` + корректный `is_active` в `/teams/{team_id}/roles`;
  - фильтрация и сортировка `/teams/{team_id}/runtime-status`;
  - `POST /questions` без публичного `created_by_user_id` + tolerant-ignore legacy поля;
  - `answer_id` в `/questions/{id}` и `/questions/{id}/status`;
  - `POST /teams/{team_id}/roles/{role_id}` (idempotent `200`, `404` mapping).
- Regression:
  - Stage5/dispatch bridge без регрессий;
  - Telegram UX regression suite зелёный.

## Closeout (Wave 2, 2026-04-08)
- Реализация:
  - `GET /api/v1/prepost_processing_tools` включён, legacy pre/post endpoint-ы убраны.
  - `GET /api/v1/skills` и `GET /api/v1/prepost_processing_tools` возвращают `source` как repo-relative POSIX path или `null`.
  - `GET /api/v1/roles/catalog` без `include_inactive` в контракте.
  - `GET /api/v1/teams/{team_id}/roles` возвращает `team_role_id`, корректный `is_active`, корректный `include_inactive`.
  - `GET /api/v1/teams/{team_id}/runtime-status` фильтрует inactive и стабильно сортируется по `team_role_id`.
  - `POST /api/v1/questions` убран публичный `created_by_user_id` (legacy поле tolerant-ignore).
  - `GET /api/v1/questions/{question_id}` и `/status` включают `answer_id`.
  - `POST /api/v1/teams/{team_id}/roles/{role_id}` реализован как идемпотентный bind.
- Gates:
  - `scripts/stage5_qa_api_gates.sh` — **PASS**.
  - `scripts/stage5_execution_bridge_gates.sh` — **PASS**.
  - blocking OpenAPI snapshot — **PASS**.
- Итог:
  - Wave 2 status: **GO**.

## Appendix: исторический аудит Wave 2 (до реализации)

### W2.1 `GET /api/v1/skills.source` -> repo-relative POSIX path или `null`
- Факт:
  - endpoint уже есть в `app/interfaces/api/routers/read_only_v1.py`;
  - source формируется через `_registry_source(...)` и сейчас возвращает `entrypoint`/fallback-строку (`app/application/use_cases/read_api.py`).
- Пробел:
  - нет вычисления относительного пути к папке навыка от корня репо;
  - `source` тип сейчас `str`, требуется `null` для non-file source.
- Точки врезки:
  - `app/application/use_cases/read_api.py` (`RegistryItem.source`, `_registry_source`);
  - `app/interfaces/api/schemas/entities.py` (`SkillDTO.source` -> nullable);
  - `app/interfaces/api/schemas/adapters.py`.
- Тесты/гейты:
  - `tests/test_ltc85_stage5_api_parity_use_cases.py`
  - `tests/test_ltc69_read_only_fastapi_contract.py`
  - `tests/test_ltc70_openapi_snapshot.py`

### W2.2 Consolidation pre/post -> `GET /api/v1/prepost_processing_tools`
- Факт:
  - сейчас есть два endpoint-а: `/pre_processing_tools` и `/post_processing_tools` (`read_only_v1.py`);
  - оба используют одну и ту же prepost registry (`read_api.py`).
- Пробел:
  - отсутствует целевой единый endpoint;
  - старые endpoint-ы всё ещё в роутере, тестах и OpenAPI snapshot.
- Точки врезки:
  - router: `app/interfaces/api/routers/read_only_v1.py`;
  - use-case: добавить unified list-функцию в `app/application/use_cases/read_api.py`;
  - DTO: unified tool DTO в `app/interfaces/api/schemas/entities.py`;
  - adapters/exports: `app/interfaces/api/schemas/adapters.py`, `__init__.py`.
- Совместимость/миграция:
  - удаление старых endpoint-ов будет контрактной корректировкой;
  - требуется обновить docs/runbook + OpenAPI snapshot + contract tests.
- Тесты/гейты:
  - `tests/test_ltc69_read_only_fastapi_contract.py`
  - `tests/test_ltc70_openapi_snapshot.py`
  - `scripts/stage5_qa_api_gates.sh`

### W2.3 `GET /api/v1/roles/catalog`: убрать `include_inactive` из контракта
- Факт:
  - router сейчас принимает `include_inactive` и прокидывает в use-case (`read_only_v1.py`);
  - use-case фактически игнорирует параметр (`list_master_roles_catalog_result`).
- Пробел:
  - query параметр остаётся в OpenAPI/доках, хотя больше не нужен.
- Точки врезки:
  - router signature: `app/interfaces/api/routers/read_only_v1.py`;
  - use-case signature cleanup: `app/application/use_cases/read_api.py`;
  - docs/tests snapshot.
- Совместимость/миграция:
  - FastAPI по умолчанию игнорирует неизвестный query-param, поэтому удаление из сигнатуры остаётся безопасным для клиентов.
- Тесты/гейты:
  - `tests/test_ltc69_read_only_fastapi_contract.py` (убрать сценарии include_inactive для catalog);
  - `tests/test_ltc70_openapi_snapshot.py`.

### W2.4 `GET /api/v1/teams/{team_id}/roles`: include_inactive semantics + `team_role_id`
- Факт:
  - `RoleDTO` сейчас не содержит `team_role_id` (`entities.py`);
  - `list_roles_for_team(..., include_inactive=True)` в storage фильтрует `WHERE tr.is_active = 1`, поэтому неактивные bindings не попадают;
  - `is_active` вычисляется комбинированно (`tr.is_active && tr.enabled && master.is_active`), что не соответствует требованию брать `team_roles.is_active`.
- Пробел:
  - `include_inactive=true` не возвращает реальные inactive bindings;
  - нет обязательного `team_role_id` в response;
  - `is_active` semantics не совпадает с требованием.
- Точки врезки:
  - storage query/modeling: `app/storage.py::list_roles_for_team`;
  - role model/DTO/adapters: `app/models.py`, `app/interfaces/api/schemas/entities.py`, `adapters.py`;
  - read use-case enrichment: `app/application/use_cases/read_api.py`.
- Тесты/гейты:
  - `tests/test_ltc69_read_only_fastapi_contract.py`
  - `tests/test_ltc78_stage5_fastapi_contract.py`
  - `tests/test_ltc85_stage5_api_parity_use_cases.py`

### W2.5 `GET /api/v1/teams/{team_id}/runtime-status`: только активные роли + сортировка по `team_role_id`
- Факт:
  - active filtering уже есть (`tr.is_active = 1`) в `list_team_role_runtime_statuses(..., active_only=True)`;
  - сортировка сейчас по `tr.role_id`, не по `team_role_id` (`app/storage.py`).
- Пробел:
  - нужно сменить порядок выдачи на `ORDER BY tr.team_role_id`.
- Точки врезки:
  - `app/storage.py::list_team_role_runtime_statuses`;
  - при необходимости тест-контракт.
- Тесты/гейты:
  - `tests/test_ltc69_read_only_fastapi_contract.py`
  - `tests/test_ltc70_openapi_snapshot.py` (если меняются schema/params — не ожидается).

### W2.6 `POST /api/v1/questions`: убрать публичный `created_by_user_id`, использовать owner context
- Факт:
  - `QaCreateQuestionRequestDTO` сейчас требует `created_by_user_id` (`entities.py`);
  - router прокидывает `payload.created_by_user_id` в use-case (`read_only_v1.py`);
  - use-case/fingerprint/storage завязаны на `created_by_user_id` (`qa_api.py`, `storage.py`).
- Пробел:
  - публичный input не соответствует новому контракту;
  - нет tolerant-ignore legacy поля в payload.
- Точки врезки:
  - request DTO+parsing: `app/interfaces/api/schemas/entities.py`, `read_only_v1.py`;
  - use-case contract/fingerprint: `app/application/use_cases/qa_api.py`;
  - tests using request payload.
- Совместимость/миграция:
  - требуется мягкий parser на boundary (legacy поле допускается и игнорируется), при этом OpenAPI без поля;
  - idempotency fingerprint должен оставаться детерминированным и не зависеть от legacy поля.
- Тесты/гейты:
  - `tests/test_ltc78_stage5_fastapi_contract.py`
  - bridge suites `ltc80/81/82` (чтобы не сломать runtime path).

### W2.7 `GET /questions/{id}` и `/status`: добавить `answer_id`
- Факт:
  - `QaQuestionDTO` уже содержит `answer_id`;
  - `QaQuestionStatusDTO` не содержит `answer_id`;
  - `get_question_result` возвращает вопрос без enrichment answer_id;
  - `get_question_status_result` тоже без answer lookup.
- Пробел:
  - field отсутствует в `/status`;
  - в `/questions/{id}` `answer_id` может оставаться `null` даже для answered, если не обогащать.
- Точки врезки:
  - `app/application/use_cases/qa_api.py` (`get_question_result`, `get_question_status_result`, `QaQuestionStatus`);
  - `app/interfaces/api/schemas/entities.py` (`QaQuestionStatusDTO`);
  - adapters mapping.
- Тесты/гейты:
  - `tests/test_ltc78_stage5_fastapi_contract.py`
  - `tests/test_ltc79_stage5_api_e2e_smoke.py`.

### W2.8 Новый bind endpoint `POST /api/v1/teams/{team_id}/roles/{role_id}`
- Факт:
  - storage уже поддерживает идемпотентный bind: `bind_master_role_to_team(team_id, role_id) -> (TeamRole, created)` (`app/storage.py`);
  - HTTP route/use-case для этой операции отсутствуют.
- Пробел:
  - нет API boundary, DTO response, status/error mapping и тестов.
- Точки врезки:
  - write use-case: `app/application/use_cases/write_api.py`;
  - router: `app/interfaces/api/routers/read_only_v1.py` (owner-only + runtime_write_guard + envelope);
  - DTO/adapters: `app/interfaces/api/schemas/entities.py`, `adapters.py`, `__init__.py`.
- Совместимость/миграция:
  - операция additive; можно вводить без влияния на существующие маршруты.
- Тесты/гейты:
  - расширить `tests/test_ltc74_write_fastapi_contract.py` и/или `tests/test_ltc69_read_only_fastapi_contract.py`;
  - `tests/test_ltc70_openapi_snapshot.py`.

### Совместимость и миграция со старых endpoint-ов
- `/pre_processing_tools` и `/post_processing_tools`:
  - будут удалены из роутера/OpenAPI в пользу `/prepost_processing_tools`;
  - миграция клиентов: прямой switch на новый endpoint в одном релизе (без grace-alias).
- `POST /questions.created_by_user_id`:
  - поле исчезает из OpenAPI, но legacy payload принимается и игнорируется для soft compatibility.
- `roles/catalog.include_inactive`:
  - удаляется из сигнатуры; лишний query param безопасно игнорируется FastAPI.

### Инварианты и контроль регрессий
- Owner-only/authz и единый error envelope сохраняются на всех изменённых/new endpoints.
- Обязательные прогоны:
  - `scripts/stage5_qa_api_gates.sh`
  - `scripts/stage5_execution_bridge_gates.sh` (если затронут `POST /questions`/bridge path).
