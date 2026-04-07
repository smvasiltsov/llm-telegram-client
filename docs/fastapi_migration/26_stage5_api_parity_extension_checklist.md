# 26. Stage 5 API Parity Extension Checklist (Telegram UI parity)

## Статус
- Текущий этап: `Finalized`.
- Реализация: `DONE (2026-04-06)`.
- Gate-статус:
  - `stage5_qa_api_gates`: **PASS**.
  - `stage5_execution_bridge_gates`: **PASS**.

## Scope (подтверждено)
- Добавить read endpoints:
  - `GET /api/v1/skills`
  - `GET /api/v1/pre_processing_tools`
  - `GET /api/v1/post_processing_tools`
- Расширить `GET /api/v1/teams/{team_id}/roles`:
  - добавить включённые `skills`, `pre_processing_tools`, `post_processing_tools`.
- Пересобрать контракт `GET /api/v1/roles/catalog` как каталог только master-role.
- Добавить write endpoint:
  - `PATCH /api/v1/roles/{role_id}` (редактирование master-role).
- Расширить `GET /api/v1/qa-journal`:
  - добавить `answer_id` (nullable).

## Endpoint contracts

### 1) `GET /api/v1/skills`
- Pagination: нет (полный список).
- Item shape: `skill_id`, `name`, `description`, `source`.
- Source: registry/каталог навыков (без team bindings).

### 2) `GET /api/v1/pre_processing_tools`
- Pagination: нет (полный список).
- Item shape: `tool_id`, `name`, `description`, `source`.

### 3) `GET /api/v1/post_processing_tools`
- Pagination: нет (полный список).
- Item shape: `tool_id`, `name`, `description`, `source`.

### 4) `GET /api/v1/teams/{team_id}/roles`
- Additive поля:
  - `skills: [{id, name}]`
  - `pre_processing_tools: [{id, name}]`
  - `post_processing_tools: [{id, name}]`
- Показывать только включённые для роли.
- Сортировка в каждом списке: стабильная по `id`.

### 5) `GET /api/v1/roles/catalog`
- Только master roles.
- Поля строго:
  - `role_id`
  - `role_name`
  - `llm_model`
  - `system_prompt`
  - `extra_instruction`
  - `has_errors`
  - `source`
- Не возвращать:
  - `is_active`
  - `is_orchestrator`
- `include_inactive` игнорируется (без `422`, для совместимости).
- `has_errors` основан на текущей catalog/validation логике.
- `source` оставляем в текущем формате проекта.

### 6) `PATCH /api/v1/roles/{role_id}`
- Разрешённые поля:
  - `role_name`
  - `llm_model`
  - `system_prompt`
  - `extra_instruction`
- Rename разрешён.
- Конфликт имени: `409`.
- Response: `200` + обновлённая master-role.
- `Idempotency-Key`: не требуется.

### 7) `GET /api/v1/qa-journal`
- Additive поле записи: `answer_id: string | null`.
- Для статусов не `answered`: `null`.

## Status/Code policy
- Новые GET endpoints: `200/401/403`.
- `PATCH /api/v1/roles/{role_id}`: `200/401/403/404/409/422`.
- Сохранить единый error envelope.

## Invariants
- `owner-only/authz`: без изменений.
- `additive-only`: без breaking-изменений существующего API.
- Без регрессий Stage 5/dispatch bridge.
- Telegram UX/поведение: без изменений.

## CI/Gates policy
- Проверки включить в текущие цепочки:
  - `scripts/stage5_qa_api_gates.sh`
  - при необходимости `scripts/stage5_execution_bridge_gates.sh`
- OpenAPI snapshot остаётся blocking в действующих gate-пайплайнах.

## Финализация поставки (этап 6)
- [x] API boundary и DTO/OpenAPI wiring для scope из раздела `Scope`.
- [x] Обновлены контракты и тесты:
  - `409` на конфликт имени в `PATCH /api/v1/roles/{role_id}`;
  - `answer_id` (nullable) в `GET /api/v1/qa-journal`;
  - сортировка и только enabled элементы в `skills/pre/post` у `GET /api/v1/teams/{team_id}/roles`.
- [x] OpenAPI snapshot обновлён (blocking).
- [x] Прогнаны blocking gates:
  - `scripts/stage5_qa_api_gates.sh`;
  - `scripts/stage5_execution_bridge_gates.sh`.

## Риски и допущения (остаточные)
- Runtime/parity extension не меняет Telegram UX и публичный контракт Stage5 Q/A lifecycle.
- `GET /api/v1/roles/catalog` использует master-role shape; `include_inactive` остаётся ignore-compatible для обратной совместимости.
- Расширение остаётся additive-only в пределах согласованного baseline.

## Итог по поставке
- Статус: **GO**.
- Переход к следующему этапу: **разрешён**.

## Этап 2. Аудит кода: точки врезки и пробелы

### R1. Новый `GET /api/v1/skills`
- Текущее состояние:
  - Endpoint отсутствует в `app/interfaces/api/routers/read_only_v1.py`.
  - В runtime уже есть источник данных: `runtime.skills_registry.list_specs()` (`app/skills/registry.py`).
- Пробел:
  - Нет API DTO и adapter-конвертера для `skill_id/name/description/source`.
  - Нет read use-case, возвращающего registry-backed список.
- Точки врезки:
  - Router: `app/interfaces/api/routers/read_only_v1.py`
  - Read use-case: `app/application/use_cases/read_api.py`
  - DTO/adapters: `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`, `app/interfaces/api/schemas/__init__.py`
  - Тесты: `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`

### R2. Новые `GET /api/v1/pre_processing_tools` и `GET /api/v1/post_processing_tools`
- Текущее состояние:
  - Endpoint-ы отсутствуют в router.
  - Источник данных существует: `runtime.prepost_processing_registry.list_specs()` (`app/prepost_processing/registry.py`).
- Пробел:
  - Нет разделения в API-контракте на pre/post списки.
  - Нет DTO для `tool_id/name/description/source`.
- Точки врезки:
  - Router: `app/interfaces/api/routers/read_only_v1.py`
  - Read use-case: `app/application/use_cases/read_api.py`
  - DTO/adapters: `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`, `app/interfaces/api/schemas/__init__.py`
  - Тесты/gates: `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`, `scripts/stage5_qa_api_gates.sh`

### R3. Расширение `GET /api/v1/teams/{team_id}/roles` включёнными `skills/pre/post`
- Текущее состояние:
  - Endpoint существует, возвращает `RoleDTO` без вложенных списков (`app/interfaces/api/schemas/entities.py`).
  - В storage есть данные для включённых связей:
    - `list_role_skills_for_team_role(..., enabled_only=True)` (`app/storage.py`)
    - `list_role_prepost_processing_for_team_role(..., enabled_only=True)` (`app/storage.py`)
- Пробел:
  - Нет расширенной модели ответа (списки `{id, name}`).
  - Нет orchestration-слоя, объединяющего роль + enabled bindings + имена из registry.
- Точки врезки:
  - Read use-case: `app/application/use_cases/read_api.py` (расширенный payload team-role view)
  - Storage usage: `app/storage.py` (reuse существующих list_* методов)
  - Router/DTO: `app/interfaces/api/routers/read_only_v1.py`, `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`
  - Regression tests: `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc78_stage5_fastapi_contract.py`

### R4. Пересборка `GET /api/v1/roles/catalog` под master-role контракт
- Текущее состояние:
  - Endpoint уже есть, но использует текущий `RoleCatalogItemDTO` с полями `is_active` и `is_orchestrator`.
  - Read use-case `list_roles_catalog_result(...)` добавляет team-derived `is_orchestrator` и фильтрует по `include_inactive`.
- Пробел:
  - Текущий shape не совпадает с новым master-role-only контрактом.
  - `role_id` отсутствует в `RoleCatalogItemDTO` и в `RoleCatalogItem` модели.
- Точки врезки:
  - Domain model: `app/models.py` (`RoleCatalogItem`)
  - Read use-case: `app/application/use_cases/read_api.py` (`list_roles_catalog_result`)
  - DTO/adapters: `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`
  - Router behavior: `app/interfaces/api/routers/read_only_v1.py` (`include_inactive` оставить как ignore-compatible)
  - Тесты/gates: `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`, `scripts/stage5_qa_api_gates.sh`

### R5. Новый `PATCH /api/v1/roles/{role_id}` (master-role mutation)
- Текущее состояние:
  - Есть только patch team binding: `PATCH /api/v1/teams/{team_id}/roles/{role_id}`.
  - В storage есть примитивы для master-role:
    - `get_role_by_id(...)`
    - `update_role_name(...)`
    - `upsert_role(...)` (upsert по `role_name`).
- Пробел:
  - Нет write use-case и DTO для patch master-role.
  - Нет явного маппинга конфликта имени `409` для rename.
  - Нет отдельного router endpoint с контрактом `200/401/403/404/409/422`.
- Точки врезки:
  - Write use-case: `app/application/use_cases/write_api.py`
  - Storage checks/update: `app/storage.py`
  - Router + error mapping: `app/interfaces/api/routers/read_only_v1.py`, `app/interfaces/api/error_mapping.py`
  - DTO/adapters: `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`, `app/interfaces/api/schemas/__init__.py`
  - Tests/gates: `tests/test_ltc74_write_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`, `scripts/stage5_qa_api_gates.sh`

### R6. `GET /api/v1/qa-journal` добавить `answer_id` (nullable)
- Текущее состояние:
  - Endpoint есть, но отдаёт `QaQuestionDTO` через `qa_question_to_dto(...)`.
  - `QaQuestionDTO` не содержит `answer_id`.
  - В storage уже есть `get_latest_answer_for_question(...)`, ответы хранятся в `answers`.
- Пробел:
  - Нет enrichment шага question->answer_id в journal view.
  - Нет DTO поля `answer_id`.
- Точки врезки:
  - Use-case (журнал): `app/application/use_cases/qa_api.py` (или отдельный read adapter слой для journal item view)
  - Storage access: `app/storage.py` (reuse get_latest_answer_for_question / query optimization при необходимости)
  - DTO/adapters/router: `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`, `app/interfaces/api/routers/read_only_v1.py`
  - Tests/gates: `tests/test_ltc78_stage5_fastapi_contract.py`, `tests/test_ltc79_stage5_api_e2e_smoke.py`, `tests/test_ltc70_openapi_snapshot.py`

### R7. В `roles/catalog` добавить обязательный `role_id`
- Текущее состояние:
  - В текущем контракте `role_id` отсутствует.
- Пробел:
  - Нет прямого маппинга от catalog role name к master role id в API payload.
- Точки врезки:
  - Read use-case `list_roles_catalog_result(...)`: резолюция `role_name -> role_id` через storage roles.
  - Models/DTO/adapters: `app/models.py`, `app/interfaces/api/schemas/entities.py`, `app/interfaces/api/schemas/adapters.py`
  - Tests/OpenAPI: `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`

### Owner-only/additive-only инварианты
- Текущее состояние:
  - Owner-only guard централизован в router (`_owner_guard`).
  - Единый error envelope есть.
  - Stage5 bridge path зависит от `POST /questions` + worker; текущие требования его не затрагивают.
- Риск-регрессии:
  - Изменение существующих DTO `RoleDTO`/`QaQuestionDTO` может затронуть существующие контракты.
- Контроль:
  - Изменения вводить additive/совместимо, а breaking shape в `roles/catalog` оформить только в пределах согласованного baseline.
  - Обязательный прогон `scripts/stage5_qa_api_gates.sh`; при затрагивании общих Stage5 путей — дополнительно `scripts/stage5_execution_bridge_gates.sh`.
