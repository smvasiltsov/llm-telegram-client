# 23. Внутренний Runtime-Execution Контракт И Breaking-Risk Зоны

## 1. Request contract (API/Bridge -> Runtime Core)
- Команда: `ExecuteQuestion`.
- Обязательные поля:
  - `question_id: str`
  - `team_id: int`
  - `target_team_role_id: int`
  - `role_id: int`
  - `execution_user_id: int`
  - `text: str`
  - `correlation_id: str`
- Условные поля:
  - `session_token: str`
    - обязателен только при `effective auth.mode=required`;
    - для `effective auth.mode=none` передаётся пустым и не требуется для dispatch.
- Источник `effective auth.mode`:
  - runtime-resolver provider/model;
  - приоритет `model override > provider default`;
  - fail-safe при сбое резолюции: `required` (deny-by-default).

## 2. Response contract (Runtime Core -> Bridge)
- Успех:
  - `answer_text: str`
  - `role_name: str | null`
  - `answer_team_role_id: int | null`
  - `append_orchestrator_feed: bool`
- Ошибка:
  - exception с machine-code семантикой (см. раздел 4).

## 3. Status contract (Question lifecycle)
- Переходы:
  - `accepted -> queued -> in_progress -> answered | failed | timeout`
- Retry/lease semantics:
  - lease TTL: `120s`;
  - requeue при lease expiry до лимита попыток;
  - лимит попыток: `3`;
  - при исчерпании -> `timeout`.
- Terminal persistence contract:
  - при `answered`: атомарный persist `question(status=answered)` + `answer` (+ `orchestrator_feed` при флаге);
  - при `failed/timeout`: persist terminal status + error code/message.

## 4. Error contract (machine codes)
- `dispatch_rejected`
  - в т.ч. `dispatch_rejected:missing_authorized_token` при `auth.mode=required`.
- `runtime_busy_conflict`
- `provider_timeout`
- `provider_error`
- `internal_execution_error`

## 5. Correlation/Idempotency contract
- `X-Correlation-Id` принимается/генерируется на API boundary и прокидывается в bridge/runtime логи.
- API idempotency:
  - `Idempotency-Key` обязателен для `POST /api/v1/questions`;
  - replay/mismatch обрабатывается до runtime dispatch.

## 6. Breaking-risk зоны при вынесении Runtime в отдельный сервис
- R1: Расхождение `created_by_user_id` и пользователя с валидным provider auth token.
- R2: Потеря/несогласованность `effective auth.mode` между API/bridge/runtime после разделения сервисов.
- R3: Неполный перенос status machine/lease semantics (риск залипания в `accepted/queued/in_progress`).
- R4: Неатомарный terminal persist (`question`/`answer`/`orchestrator_feed`) на межсервисных границах.
- R5: Неполная propagation `correlation_id` между API и Runtime service.
- R6: Изменение error taxonomy (machine codes) и рассинхронизация error mapping.
- R7: Нарушение single-runner policy/lock semantics при масштабировании runtime.
- R8: Риск регрессии при удалении legacy fallback после thin-client cutover (нужен контролируемый rollout и метрики ошибок adapter-контракта).
- R9: Несовместимость idempotency/retry между API и runtime queue при сетевых ретраях.
- R10: Неполная миграция observability/CI gates, из-за чего регрессии runtime пути не блокируют merge.
