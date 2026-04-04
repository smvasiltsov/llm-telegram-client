# 03. Рефакторинг и целевая FastAPI-архитектура

## 1. Цель документа
- Определить минимально необходимый pre-API рефакторинг и целевую структуру FastAPI-слоя для управления текущим функционалом без регрессии runtime-семантики.

## 2. Pre-API рефакторинг (обязательно до API)

### P0 (блокеры)
1. Выделить application-layer use-cases из Telegram handlers.
- Сейчас ключевые операции живут в `handlers/*` и завязаны на `Update/ContextTypes`.
- Нужно вынести доменные команды в чистые сервисы/use-cases с интерфейс-независимыми DTO.
- Источники: `app/handlers/messages_group.py:40`, `app/handlers/messages_private.py:259`, `app/handlers/callbacks.py:1`.

2. Ввести единый error model для API.
- Сейчас ошибки разнородны (`ValueError`, текстовые ответы в чат).
- Нужен нормализованный слой ошибок (code, message, details, http_status).
- Источники: `app/storage.py:1998`, `app/storage.py:2209`, `app/handlers/commands.py:109`.

3. Зафиксировать транзакционные границы для составных команд.
- Сценарии reset/remove->add/session/provider fields состоят из серии независимых `Storage` операций.
- Нужно определить атомарные unit-of-work для API-команд.
- Источники: `app/core/use_cases/team_roles.py:135`, `app/core/use_cases/team_roles.py:152`, `app/storage.py:1814`, `app/storage.py:3573`.

4. Вынести authz/policy из Telegram owner-check в переиспользуемый слой.
- Проверки `owner_user_id` разбросаны по handlers/callbacks.
- Для FastAPI требуется единая policy dependency (RBAC/owner-only на старте).
- Источники: `app/handlers/commands.py:30`, `app/handlers/callbacks.py:42`, `app/interfaces/telegram/adapter.py:76`.

### P1 (высокий приоритет)
1. Стабилизировать контракты runtime-операций (queue/busy/pending) для API.
- Явно описать какие операции API могут инициировать pending/replay и как отражается статус.
- Источники: `app/services/role_pipeline.py:1250`, `app/services/role_runtime_status.py:98`, `app/services/role_dispatch_queue.py:45`.

2. Декомпозировать `RuntimeContext` на API-friendly dependencies.
- Сейчас `RuntimeContext` агрегирует всё (storage/router/queue/plugins/tools).
- Для API слоя нужно ограничить зависимость endpoint-ов строго нужными сервисами.
- Источник: `app/runtime.py:24`.

3. Добавить сериализуемые DTO для доменных сущностей и операций.
- Сейчас наружу в основном идут dataclass + ad-hoc структуры.
- Для API нужен единый schema contract (Pydantic).
- Источники: `app/models.py:6`, `app/storage.py:2277`, `app/storage.py:2230`.

### P2 (желательно)
1. Улучшить observability до API-grade (correlation id, метрики по операциям).
- Сейчас много полезных логов, но без единой метрик-модели.
- Источники: `app/services/role_pipeline.py:1321`, `app/handlers/messages_common.py:76`.

2. Подготовить in-memory runtime компоненты к multi-instance режиму.
- Очередь исполнения по ролям in-memory.
- Для API-кластера понадобится стратегия (single-runner, sticky, или внешняя очередь).
- Источник: `app/services/role_dispatch_queue.py:31`.

## 3. Целевая структура FastAPI

### 3.1 Routers
- `routers/teams.py`:
  - команды, channel bindings, список ролей в команде.
- `routers/roles.py`:
  - master roles, team role overrides, enable/mode/model/prompt operations.
- `routers/skills.py`:
  - enable/disable/config skills на team-role.
- `routers/prepost.py`:
  - CRUD для pre/post processing bindings.
- `routers/sessions.py`:
  - reset/list role sessions, message history.
- `routers/runtime.py`:
  - runtime status, lock groups, queue diagnostics.

### 3.2 Services (application layer)
- `services/team_service.py`
- `services/team_role_service.py`
- `services/skill_binding_service.py`
- `services/prepost_binding_service.py`
- `services/session_service.py`
- `services/runtime_ops_service.py`

Каждый сервис использует `Storage` + (при необходимости) runtime services, но не зависит от Telegram Update/Context.

### 3.3 Schemas (Pydantic)
- `schemas/common.py` (ErrorResponse, Pagination, Id wrappers)
- `schemas/team.py`
- `schemas/role.py`
- `schemas/skill.py`
- `schemas/session.py`
- `schemas/runtime.py`

### 3.4 Dependencies
- `deps/auth.py`: policy/owner-only guard.
- `deps/runtime.py`: получение typed зависимостей из runtime контейнера.
- `deps/validation.py`: общие проверки идентификаторов и invariant checks.

### 3.5 Error model
- Базовый формат:
  - `code` (stable machine code),
  - `message` (human-readable),
  - `details` (field/path/context),
  - `trace_id`.
- Маппинг доменных исключений на HTTP-коды:
  - not found -> 404,
  - validation/invariant -> 422/409,
  - unauthorized/forbidden -> 401/403,
  - runtime busy/conflict -> 409/423.

## 4. Контуры API (минимальный контракт)
- Teams/bindings:
  - `GET /teams`
  - `GET /teams/{team_id}`
  - `GET /teams/{team_id}/bindings`
- Team roles:
  - `GET /teams/{team_id}/roles`
  - `PATCH /teams/{team_id}/roles/{role_id}` (enabled/mode/display/model/overrides)
  - `POST /teams/{team_id}/roles/{role_id}/reset-session`
  - `DELETE /teams/{team_id}/roles/{role_id}` (deactivate binding)
- Skills/prepost:
  - `GET /team-roles/{team_role_id}/skills`
  - `PUT /team-roles/{team_role_id}/skills/{skill_id}`
  - `GET /team-roles/{team_role_id}/prepost`
  - `PUT /team-roles/{team_role_id}/prepost/{prepost_id}`
- Runtime:
  - `GET /teams/{team_id}/runtime-status`
  - `GET /team-roles/{team_role_id}/runtime-status`

## 5. Совместимость и миграция
- Не ломать текущий Telegram-интерфейс: FastAPI как дополнительный interface adapter.
- Переиспользовать существующий `Storage` и runtime services, постепенно перенося бизнес-ветки из handlers в use-cases.
- Использовать существующие поведенческие тесты как regression baseline и добавить API contract tests отдельно.
- Источники:
  - `app/interfaces/telegram/adapter.py:33`
  - `app/interfaces/runtime/loader.py:14`
  - `app/interfaces/runtime/runner.py:23`
  - `tests/test_ltc18_pipeline_busy_semantics.py:1049`

## 6. Трассируемость (код/тесты)
- Runtime container: `app/runtime.py`, `app/app_factory.py`.
- Interface layer: `app/interfaces/telegram/adapter.py`, `app/interfaces/runtime/*`.
- Domain/store: `app/storage.py`, `app/models.py`.
- Current use-cases: `app/core/use_cases/*`.
- Behavioral baseline tests: `tests/test_ltc13_inheritance_override.py`, `tests/test_ltc18_pipeline_busy_semantics.py`, `tests/test_core_team_roles_use_cases.py`, `tests/test_root_dir_pending_flow.py`.
