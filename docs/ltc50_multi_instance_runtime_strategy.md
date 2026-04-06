# LTC-50: Multi-instance runtime dispatch strategy

## Scope

- `app/services/role_dispatch_queue.py`
- `app/services/role_pipeline.py`
- runtime/config wiring:
  - `app/config.py`
  - `app/runtime.py`
  - `app/app_factory.py`
  - transport/API health access:
    - `app/interfaces/telegram/adapter.py`
    - `app/interfaces/api/dependencies.py`

Соседние in-memory компоненты (`role_runtime_status`, `pending_store`, `message_buffer`) не рефакторились массово.

## Реализованная стратегия

### Modes

1. `single-instance` (default)
- Поведение как раньше.
- `dispatch_is_runner` принудительно `true`.

2. `single-runner`
- Явный runner назначается через config (`dispatch.is_runner`).
- Non-runner instance не исполняет dispatch и возвращает контролируемый rejection.

### Что добавлено

1. Конфиг:
- `dispatch.mode`: `single-instance | single-runner`
- `dispatch.is_runner`: `bool`

2. Runtime state:
- `RuntimeContext.dispatch_mode`
- `RuntimeContext.dispatch_is_runner`
- `runtime_dispatch_health` в `bot_data` (`mode`, `is_runner`)

3. Policy abstraction:
- `app/services/dispatch_policy.py`
  - `SingleInstanceDispatchPolicy`
  - `SingleRunnerDispatchPolicy`
  - `UnsupportedDispatchPolicy`
  - extension points для `sticky` / `external-queue`

4. Queue integration:
- `RoleDispatchQueueService` принимает mode/runner.
- `acquire_execution_slot(...)` возвращает `QueueGrant.accepted/reason`.
- Non-runner rejection не делает enqueue.

5. Pipeline/use-case behavior:
- rejection из queue поднимается как `DispatchPolicyRejectedError`
- маппинг в `runtime_orchestration.execute_run_chain_operation(...)`:
  - `runtime.busy_conflict` (LTC-43 compatible)
  - details: `mode`, `runner`, `reason`, `request_id`, `correlation_id`

6. Observability (LTC-49 integration):
- метки `mode` и `runner` добавлены в operation metrics
- rejection metric:
  - `runtime_dispatch_rejected_total`

7. Startup/health signal:
- startup log в telegram bootstrap:
  - `Runtime dispatch health mode=<...> is_runner=<...>`
- API provider:
  - `provide_runtime_dispatch_health(...)`

## Guarantees

1. UX/тексты/callback_data/порядок ответов не менялись.
2. FIFO/busy/pending semantics сохранены для runner/single-instance путей.
3. `single-instance` остаётся безопасным fallback для локалки/тестов.
4. Rejection в non-runner — явный и контролируемый (без silent execution).

## Risks / Limitations

1. Нет distributed election (runner задаётся вручную конфигом).
2. Нет межинстансной глобальной очереди/персистентного broker-а.
3. Non-runner не берёт работу; нужна внешняя топология, где runner действительно принимает трафик runtime.
4. `sticky`/`external queue` не реализованы, только подготовлены как extension points.

## Extension points (next milestones)

1. `sticky` routing policy (instance-affinity by `team_role_id`/`chat_id` hash).
2. External broker-backed dispatch policy (`Redis/Rabbit/NATS` и т.п.).
3. Leader lease/election вместо ручного `is_runner`.
