# LTC-47: Декомпозиция RuntimeContext на API-friendly dependencies

## Step 1 — Baseline инвентаризация

## 1) Текущий состав RuntimeContext

`RuntimeContext` объявлен в `app/runtime.py` и содержит 50+ полей (storage, auth, runtime queue/status, pending stores, LLM/services, registries, tools/plugins, rollout flags, mutable runtime state).

Ключевая проблема: один объект одновременно хранит
- domain/service зависимости,
- mutable runtime-state,
- interface/runtime flags,
- transport-level настройки.

Это усложняет узкий DI для API endpoint-ов.

## 2) Где RuntimeContext создаётся и пробрасывается

- Сборка: `app/app_factory.py::build_runtime(...)`
- Инъекция в transport: `app/interfaces/telegram/adapter.py` через `application.bot_data["runtime"]`
- Доступ в handlers/services: `app/handlers/messages_common.py::_runtime(...)`

## 3) Фактические потребители в целевом scope

### `messages_group`
Использует: `storage`, `message_buffer`, `pending_store`, `cipher`, `bot_username`, `owner_user_id`, `require_bot_mention`.

### `messages_private`
Использует: `storage`, `auth_service`, `pending_store`, `pending_user_fields`, `pending_prompts`, `pending_role_ops`, `private_buffer`, `provider_models`, `provider_registry`, `tool_service`, `pending_bash_auth`, `bash_cwd_by_user`, `cipher`, `tools_bash_password`.

### `callbacks`
Использует: `storage`, `pending_prompts`, `pending_role_ops`, `provider_registry`, `provider_models`, `provider_model_map`, `skills_registry`, `prepost_processing_registry`, `role_catalog`.

### `role_pipeline`/runtime orchestration (прямой consumer)
Использует: `storage`, `session_resolver`, `llm_executor`, `provider_registry`, `provider_models`, `provider_model_map`, `default_provider_id`, `pending_store`, `skills_service`, `prepost_processing_registry`, `plugin_manager`, `allow_raw_html`, `formatting_mode`.

## 4) Базовая декомпозиция зависимостей (целевые dependency groups)

1. `AuthzDeps`
- `authz_service`

2. `RuntimeOrchestrationDeps`
- `storage`, `session_resolver`, `llm_executor`, `provider_*`, `default_provider_id`

3. `QueueStatusDeps`
- `role_dispatch_queue_service`, `role_runtime_status_service`, `free_transition_delay_sec`

4. `StorageUowDeps`
- `storage` (с UoW-инвариантами)

5. `PendingReplayDeps`
- `pending_store`, `pending_user_fields`, `pending_prompts`, `pending_role_ops`

6. `ToolingDeps` (временный mixed-mode)
- `tool_service`, `pending_bash_auth`, `bash_cwd_by_user`, `tools_bash_password`

## 5) Риски baseline

- Mutable maps (`pending_prompts`, `pending_role_ops`, `pending_bash_auth`, `bash_cwd_by_user`) сейчас не инкапсулированы контрактами.
- `RuntimeContext` используется как service locator; порядок инициализации не выражен типами.
- Прямые обращения к runtime из pipeline и handlers мешают узкому FastAPI dependency graph.

## 6) Что идёт в Step 2

- Создать `app/application/dependencies/*`.
- Вынести dataclass providers + accessor-методы с `Result/AppError` на внешней границе.
- Подготовить migration wiring `RuntimeContext -> dependency providers` без UX-изменений.

## Step 2 — Dependency layer (добавлено)

Реализованы новые модули:
- `app/application/dependencies/contracts.py`
- `app/application/dependencies/providers.py`
- `app/application/dependencies/__init__.py`

Что добавлено:
- Узкие dependency-контракты: `AuthzDependencies`, `RuntimeOrchestrationDependencies`, `QueueStatusDependencies`, `StorageUowDependencies`, `PendingReplayDependencies`, `ToolingDependencies`.
- Единый provider-контракт `RuntimeDependencyProvider`.
- Реализация `RuntimeContextDependencyProvider` с boundary-обёрткой `Result` и нормализованной ошибкой при отсутствии зависимости.

Переход на эти accessors в handlers/wiring выполняется в следующих шагах (Step 3+).

## Step 3 — Core dependency access layer

Добавлен модуль:
- `app/application/dependencies/access.py`

Что реализовано:
- единый вход: `resolve_provider_from_bot_data(bot_data)`
- узкие accessor-функции по dependency-группам:
  - `resolve_authz_dependencies`
  - `resolve_runtime_orchestration_dependencies`
  - `resolve_queue_status_dependencies`
  - `resolve_storage_uow_dependencies`
  - `resolve_pending_replay_dependencies`
  - `resolve_tooling_dependencies`

Инвариант:
- на внешней границе dependency-layer возвращается `Result[...]`;
- отсутствие runtime/provider не пробрасывается raw exception-ом.

## Step 4 — Bootstrap wiring (mixed-mode)

Изменения:
- `app/runtime.py`
  - в `RuntimeContext` добавлено поле `dependency_provider`
  - `to_bot_data()` теперь публикует:
    - `runtime` (как раньше)
    - `runtime_dependencies` (новый dependency provider, если доступен)
- `app/app_factory.py`
  - после сборки `RuntimeContext` создаётся и подключается `build_runtime_dependency_provider(runtime)`

Результат:
- старый доступ через `runtime` сохранён (backward compatible),
- новый dependency-entrypoint подключён на bootstrap-уровне и готов к поэтапной миграции consumers.

## Step 5 — Миграция `messages_group`

`app/handlers/messages_group.py` переведён на dependency-access точки:
- storage: `resolve_storage_uow_dependencies(...)`
- pending store: `resolve_pending_replay_dependencies(...)`
- cipher (для `build_group_flush_plan`): `resolve_runtime_orchestration_dependencies(...)`

Сохранён mixed-mode fallback:
- при недоступном dependency provider используется legacy `runtime.*`.
- внешний UX/flow не менялся.

## Step 6 — Миграция `messages_private`

`app/handlers/messages_private.py` переведён на dependency-access точки:
- storage: `resolve_storage_uow_dependencies(...)`
- pending/replay state: `resolve_pending_replay_dependencies(...)`
- runtime orchestration deps (`cipher`, `provider_models`, `provider_registry`)
- tooling deps (`tool_service`, `pending_bash_auth`, `bash_cwd_by_user`, `tools_bash_password`)

Сохранён mixed-mode fallback:
- helper-resolver'ы возвращают legacy `runtime.*`, если provider недоступен.
- поведение pending/token/private-flow и UX-сообщения не менялись.

## Step 7 — Миграция `callbacks` и `telegram adapter`

Изменения в `app/handlers/callbacks.py`:
- добавлены dependency-access resolvers для:
  - `storage` (`resolve_storage_uow_dependencies`)
  - `pending maps` (`resolve_pending_replay_dependencies`)
  - `provider data` (`resolve_runtime_orchestration_dependencies`)
- `handle_callback` переведён на эти access points для `storage` и очистки pending state;
- `_handle_action` и `_handle_set_model` используют резолвнутые `provider_model_map/provider_registry` и pending maps;
- добавлены безопасные fallback-и для тестовых контекстов без `application.bot_data`.

Изменения в `app/interfaces/telegram/adapter.py`:
- резолв `storage` и tooling-флагов/пароля через `runtime.dependency_provider` (`storage_uow()`, `tooling()`) с fallback на `runtime.*`.

Результат:
- callbacks/adapter используют dependency-layer как primary path, сохраняя backward-compatible mixed-mode.

## Step 8 — FastAPI-ready dependency provider + DI tests

Добавлены модули:
- `app/interfaces/api/dependencies.py`
- `app/interfaces/api/__init__.py`

Что реализовано:
- FastAPI-ready app-state provider API (без endpoint-ов):
  - `attach_runtime_dependencies_to_app_state(app.state, runtime)`
  - `provide_runtime_dependency_provider(app.state)`
  - `provide_*_dependencies(app.state)` для `authz/orchestration/queue/storage/pending/tooling`
- Контракт внешней границы: `Result[...]` (без raw exception наружу).

Добавлены targeted тесты:
- `tests/test_ltc47_dependency_providers.py`
  - bot_data wiring (`runtime_dependencies`)
  - app.state runtime->provider resolution
  - attach helper корректно поднимает dependency provider.
