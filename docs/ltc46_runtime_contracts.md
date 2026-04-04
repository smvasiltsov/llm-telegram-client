# LTC-46: Стабилизация runtime-контрактов (queue/busy/pending)

## Scope

Документ фиксирует API-ready контракт runtime-операций для приоритетных путей:
- `run_chain`
- `dispatch_mentions`
- `send_orchestrator_post_event`
- `pending replay`

Фактическая реализация опирается на:
- `app/application/contracts/runtime_ops.py`
- `app/application/use_cases/runtime_orchestration.py`
- `app/services/role_pipeline.py`
- `app/services/role_dispatch_queue.py`
- `app/services/role_runtime_status.py`

## Контракт операции

`RuntimeOperationRequest` / `RuntimeOperationResult` / `RuntimeTransition` (dataclass DTO):
- объявлены в `app/application/contracts/runtime_ops.py`
- используются через application use-case `execute_run_chain_operation(...)` (`app/application/use_cases/runtime_orchestration.py`)

Нормализованные operation-id:
- `runtime.run_chain`
- `runtime.dispatch_mentions`
- `runtime.orchestrator_post_event`
- `runtime.pending_replay`

Нормализованные runtime-state:
- `queued`
- `busy`
- `pending`
- `free`

## Единый orchestration path

Для всех целевых операций используется единый queue-slot путь:
- `_queue_execution_scope(...)` в `app/services/role_pipeline.py`
- гарантирует FIFO-slot acquisition/release на `team_role_id`
- ожидание `busy -> free` перед выполнением через `_wait_until_team_role_is_free(...)`

Это убирает разношерстные ветки "роль занята" и даёт одинаковую семантику ожидания.

## Матрица trigger -> transition -> Result/Error

| Operation | Trigger | Success transition | Error transition | Result flags |
|---|---|---|---|---|
| `runtime.run_chain` | `group` | `queued -> busy -> free` (`response_sent`) | `busy -> pending` (`delivery_failed` или `unauthorized_pending_saved`) | `completed`, `queued`, `busy_acquired`, `pending_saved` |
| `runtime.dispatch_mentions` | `group` | `queued -> busy -> free` | `busy -> pending` | как выше |
| `runtime.orchestrator_post_event` | `group` | `queued -> busy -> free` | `busy -> pending` | как выше |
| `runtime.pending_replay` | `pending` | `queued -> busy -> free` | `busy -> pending` (`replay_failed`) | `replay_scheduled` + базовые флаги |

Источник таблицы переходов:
- `RUNTIME_OPERATION_TRANSITION_TABLE` в `app/application/use_cases/runtime_orchestration.py`

Формирование transition-фактов:
- `_build_runtime_transitions(...)` в `app/application/use_cases/runtime_orchestration.py`

## Error model (LTC-43 integration)

Runtime-коды для API-ready конфликтов/ошибок:
- `runtime.busy_conflict` (`409`)
- `runtime.pending_exists` (`409`)
- `runtime.replay_failed` (`424`)

Реестр кодов:
- `app/application/contracts/errors.py`

Use-case оборачивает runtime exception в `Result.fail`:
- для `runtime.pending_replay` fallback -> `runtime.replay_failed`
- для прочих runtime operation -> `internal.unexpected`

## Интеграция в consumers

Переход с прямого вызова pipeline на application use-case выполнен в:
- `app/handlers/messages_group.py`
- `app/handlers/messages_private.py`

Это фиксирует единый API-ready контракт результата для group/private runtime-flow.

## Ограничения (явно зафиксированные)

1. Очередь остаётся in-process (`RoleDispatchQueueService`), без персистентности через restart.
2. `RuntimeOperationResult.transitions` сейчас агрегируются на уровне operation (без полного списка по каждому role dispatch внутри `@all`).
3. Полноценная внешняя FSM-библиотека не вводилась; используется таблица + контрактные тесты.

## Тестовое подтверждение

- `tests/test_ltc46_runtime_error_codes.py` — стабильность runtime error codes/status.
- `tests/test_ltc46_runtime_transitions_contract.py` — контракт transition table + success/error transition facts.
- `tests/test_ltc18_pipeline_busy_semantics.py` — регресс FIFO/busy/pending semantics.
- `tests/test_ltc42_group_runtime_use_cases.py`
- `tests/test_ltc42_private_pending_use_cases.py`

