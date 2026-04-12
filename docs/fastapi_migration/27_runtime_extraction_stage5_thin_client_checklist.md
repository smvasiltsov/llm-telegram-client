# 27. Stage Runtime Extraction — Этап 5 (Telegram Thin Client Baseline)

## Статус
- `Этап 5`: `BASELINE FIXED` (точки выноса определены, реализация pending).
- `Шаг 4 (compat/invariants)`: `VERIFIED` (gold-сценарии и gate-прогоны без регрессий).
- `Шаг 5 (DoD block)`: `VERIFIED` (thin-path tests + gates зелёные).

## Scope baseline
- Обязательные handlers:
  - `app/handlers/messages_group.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/messages_common.py` (только runtime-orchestration helper-ветки)
- Callback handlers:
  - `app/handlers/callbacks.py` проверен;
  - runtime orchestration path (dispatch/execute flow) не обнаружен;
  - вынос runtime-orchestration из callback handlers в рамках этапа 5 не требуется.

## Точки выноса runtime-orchestration

### 1) Group flow
- `app/handlers/messages_group.py:216`:
  - прямой вызов `execute_run_chain_operation(...)` из handler-path.
- `app/handlers/messages_group.py:185-213`:
  - orchestration decision-план (`skip/send_hint/request_token/dispatch_chain`) с ветвлением dispatch.
- `app/handlers/messages_group.py:229-233`:
  - orchestration execution flags (`save_pending_on_unauthorized`, `allow_orchestrator_post_event`, `chain_origin`).

### 2) Private flow (pending replay + dispatch)
- `app/handlers/messages_private.py:875-946`:
  - orchestration в `_process_pending_message_for_user(...)`:
    - replay dispatch planning (`build_pending_replay_dispatch_plan`);
    - token/request/skip/dispatch branch logic;
    - прямой вызов `execute_run_chain_operation(...)`.
- `app/handlers/messages_private.py:948-960`:
  - post-dispatch orchestration completion handling (pending replay consistency path).

### 3) Common helpers (runtime dependencies)
- `app/handlers/messages_common.py:28-29`:
  - прямой доступ handlers к `RuntimeContext` через `bot_data["runtime"]`.
- `app/handlers/messages_common.py:181-221`:
  - provider/session recovery helper path (`llm_router`/`llm_executor`) в handler-layer.

## Thin-client boundary (для шага 2+)
- Остаётся в handlers:
  - приём апдейта;
  - базовая валидация user input;
  - отправка Telegram ответа.
- Выносится в runtime adapter contract:
  - dispatch/queue/status transitions;
  - role routing/tag decision logic;
  - prompt enrichment (skills/prepost/system prompt);
  - provider/model resolution + execution;
  - retry/replay/lease execution flow.

## DoD tracking (этап 5)
- [x] В Telegram handlers отсутствует runtime orchestration логика.
- [x] Вызовы runtime идут только через единый adapter-контракт.
- [x] Telegram UX не изменён (golden scenarios pass).
- [x] Owner-only/контрактные инварианты не нарушены.

## Минимальный чеклист шага 5 (результаты)
- [x] Добавлен thin-client gate: `scripts/stage5_thin_client_gates.sh`.
- [x] Обновлён fallback/feature-flag тест: `tests/test_ltc87_telegram_runtime_client.py`.
- [x] Прогон thin-client gate: `bash scripts/stage5_thin_client_gates.sh` — `OK`.
- [x] Прогон baseline gate: `bash scripts/stage5_qa_api_gates.sh` — `OK`.
- [x] Прогон bridge gate: `bash scripts/stage5_execution_bridge_gates.sh` — `OK`.

## Финальный итог этапа 5 (thin-client)
- GO/NO-GO: `GO`.
- Что закрыто:
  - Telegram handlers работают через единый runtime adapter-контракт;
  - golden UX-сценарии без регрессий;
  - owner-only и контрактные инварианты сохранены.
- Остаточные риски:
  - single-instance runtime/bridge ограничение остаётся;
  - legacy fallback path нужно убрать контролируемо на следующем этапе runtime extraction.
