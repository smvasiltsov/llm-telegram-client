# LTC-46 Step 1: Инвентаризация runtime-flow (queue/busy/pending/replay)

## Приоритетные точки входа
- `run_chain`: `app/services/role_pipeline.py:1250`
- `dispatch_mentions`: `app/services/role_pipeline.py:1005`
- `send_orchestrator_post_event`: `app/services/role_pipeline.py:810`
- `pending replay`: `app/handlers/messages_private.py:742`

## Текущая фактическая логика (по коду)
1. Queue-slot (FIFO per `team_role_id`)
   - Acquire: `RoleDispatchQueueService.acquire_execution_slot(...)` (`app/services/role_dispatch_queue.py:45`)
   - Release: `RoleDispatchQueueService.release_execution_slot(...)` (`app/services/role_dispatch_queue.py:82`)
   - Во всех трёх runtime-path queue используется напрямую (дублируемый шаблон acquire/wait/release).
2. Busy/free runtime-status
   - Poll/wait до free: `_wait_until_team_role_is_free(...)` (`app/services/role_pipeline.py:165`)
   - Release delayed/immediate:
     - стандартный release: `_release_busy_for_role(...)` (`app/services/role_pipeline.py:196`) -> `RoleRuntimeStatusService.release_busy(...)` (`app/services/role_runtime_status.py:125`)
     - immediate release на `MissingUserField`: `_release_busy_for_role_immediate(...)` (`app/services/role_pipeline.py:218`)
   - Cleanup/finalize: `RoleRuntimeStatusService.cleanup_stale/finalize_due_releases` (`app/services/role_runtime_status.py:165`, `:172`)
3. Pending/replay
   - Pending save при missing field: `_handle_missing_user_field(...)` (`app/handlers/messages_common.py:64`) -> `pending.save(...)` + `pending_fields.save(...)`
   - Pending replay execution: `_process_pending_message_for_user(...)` (`app/handlers/messages_private.py:742`) -> повторный `run_chain(..., chain_origin='pending')`
   - Replay-plan и retry-budget: `build_pending_field_replay_plan(...)` (`app/handlers/messages_private.py:294`)

## Подтверждение тестами (baseline)
- Pending/replay и missing-field budget:
  - `tests/test_ltc42_private_pending_use_cases.py`
  - `tests/test_root_dir_pending_flow.py`
  - `tests/test_ltc18_pipeline_busy_semantics.py`
- Busy/queue/status semantics:
  - `tests/test_ltc18_runtime_status_service.py`
  - `tests/test_ltc18_storage_status_api.py`
  - `tests/test_ltc18_pipeline_busy_semantics.py`

## Выявленные разрывы и дубли orchestration (для следующих шагов)
1. Дублирование orchestration-шаблона
   - `run_chain`, `dispatch_mentions`, `send_orchestrator_post_event` повторяют одинаковые блоки:
     - queue acquire
     - wait-until-free
     - exception mapping (`MissingUserField`, unauthorized, delivery failed)
     - queue release
2. Неединый контракт результата
   - Runtime-paths в основном side-effect based (`None`/bool/исключения), отсутствует единый `Result/AppError` для queue/busy/pending операций.
3. Несогласованный уровень API-контракта для pending/replay
   - `pending/replay` ветка распределена между `messages_common.py`, `messages_private.py` и `role_pipeline.py`; единый orchestration entrypoint отсутствует.
4. Error-domain runtime конфликтов не формализован
   - Конфликты `busy/pending/replay` логируются/обрабатываются локально, но не имеют стабильного набора error-codes API-ready.
5. Ограничение очереди
   - Очередь in-process (`RoleDispatchQueueService` в памяти); это текущая техническая граница, не API-SLA.

## Результат шага
- Базовый runtime-контур и точки интеграции зафиксированы.
- Сформирован список конкретных разрывов, которые закрываются в шагах 2–5 LTC-46.
