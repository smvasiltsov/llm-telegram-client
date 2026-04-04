# LTC-49: API-grade observability (correlation id + metrics)

## Scope

- `app/handlers/messages_common.py`
- `app/services/role_pipeline.py`
- Прямые consumers runtime-flow:
  - `app/handlers/messages_group.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/callbacks.py`
  - `app/application/use_cases/runtime_orchestration.py`

Покрытые операции:
- `runtime.run_chain`
- `runtime.dispatch_mentions`
- `runtime.orchestrator_post_event`
- `runtime.pending_replay`

Вне scope:
- startup/reconcile observability
- storage/UoW metrics

## Реализовано

### 1) Observability contracts

Добавлен контрактный слой:
- `app/application/contracts/observability.py`

Состав:
- `ObservabilityContext`
- `MetricsPort` (protocol)
- `NoopMetricsPort`
- `LoggingMetricsPort`
- `OperationTimer`
- `sanitize_metric_labels(...)`
- `build_operation_labels(...)`

Инварианты labels:
- разрешены только: `operation`, `result`, `error_code`, `transport`
- нормализация в lower-case safe-token
- ограничение длины значения
- произвольные keys (включая `user_id`, `text`) отбрасываются

### 2) Correlation lifecycle

Добавлен модуль:
- `app/application/observability/correlation.py`

Возможности:
- `new_correlation_id()` (`uuid4().hex`)
- `ensure_correlation_id(...)` (reuse external/existing or generate)
- `set/get/clear` helpers
- `correlation_scope(...)` на `contextvars`

### 3) Correlation propagation в runtime-flow

- `messages_common`:
  - `_ensure_update_correlation_id(...)`
  - `_ensure_runtime_correlation_id(...)`
- `messages_group.handle_group_buffered(...)`: correlation_id инициализируется на входе update
- `messages_private.handle_private_message(...)`: correlation_id инициализируется на входе update
- `callbacks.handle_callback(...)`: correlation_id инициализируется на входе callback update
- `execute_run_chain_operation(...)`: принимает `correlation_id`, устанавливает context fallback
- `role_pipeline`:
  - `run_chain(...)`
  - `execute_role_request(...)`
  - `dispatch_mentions(...)`
  - `send_orchestrator_post_event(...)`
  принимают/прокидывают `correlation_id`

### 4) Метрики операций

Инструментация добавлена в:
- `app/application/use_cases/runtime_orchestration.py`
- `app/services/role_pipeline.py`

События:
- `runtime_operation_total`:
  - `result=started|success|failed`
- `runtime_operation_latency_ms`:
  - timer на operation completion/failure
- `runtime_pending_replay_total`:
  - `started|success|failed` для `runtime.pending_replay`
- `runtime_queue_wait_ms`:
  - latency FIFO wait при `queue_grant.queued`
- `runtime_busy_conflict_total`:
  - фиксируется при busy-blocker wait loop

Источник `error_code`:
- интеграция с `LTC-43` через `Result/AppError`

## Матрица `operation -> logs/metrics/tags`

| Operation | Основные логи | Метрики | Labels |
|---|---|---|---|
| `runtime.run_chain` | group/private routing + queue/busy/service logs | `runtime_operation_total`, `runtime_operation_latency_ms`, `runtime_queue_wait_ms`, `runtime_busy_conflict_total` | `operation`, `result`, `error_code`, `transport=telegram` |
| `runtime.dispatch_mentions` | delegation detect/send/skip logs | `runtime_queue_wait_ms`, `runtime_busy_conflict_total` | те же low-cardinality labels |
| `runtime.orchestrator_post_event` | post-event send/parse/fallback logs | `runtime_queue_wait_ms`, `runtime_busy_conflict_total` | те же low-cardinality labels |
| `runtime.pending_replay` | pending replay path logs | `runtime_operation_total`, `runtime_operation_latency_ms`, `runtime_pending_replay_total` | те же low-cardinality labels |

## Совместимость

- Telegram UX/тексты/порядок/callback_data не менялись.
- FIFO/busy/pending семантика сохранена.
- Внешние error-контракты не менялись.

## Ограничения и TODO

1. Метрики пока через абстрактный port (`Noop/Logging`), без Prometheus endpoint.
2. `correlation_id` не маппится в W3C `traceparent` в этой задаче.
3. Startup/reconcile observability остаётся отдельной задачей.
