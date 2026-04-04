# LTC-61: Root Cause / Fix / Verification / Risks

## Root cause
- В group-path после `flush -> dispatch_chain` выполнялся `storage.resolve_team_role_id(..., ensure_exists=True)`.
- При отсутствии team-role binding внутри `resolve_team_role_id` вызывался write `ensure_team_role`.
- Этот write происходил вне `Storage.transaction(...)`, поэтому с включённым guard падал `StorageTransactionRequiredError: write_outside_transaction operation=ensure_team_role`.

## Fix
- В `app/services/role_pipeline.py` добавлен helper `_resolve_team_role_id_for_dispatch(...)`, который оборачивает `resolve_team_role_id(..., ensure_exists=True)` в `storage.transaction(immediate=True)`.
- Все dispatch-path точки, где нужен `queue_team_role_id`, переведены на этот helper:
  - `run_chain`
  - `dispatch_mentions`
  - `send_orchestrator_post_event`
  - fallback в `execute_role_request` для `group_role.team_role_id is None`
- UoW не расширяли на весь dispatch (чтобы не конфликтовать с busy/status транзакциями).

## Verification
- Добавлен регрессионный тест: `tests/test_ltc61_group_dispatch_uow_guard.py`
  - Проверяет, что `ensure_team_role` в group dispatch вызывается только при активной транзакции.
  - Проверяет успешную обработку group mention без исключений.
- Прогонены тесты:
  - `python3 -m unittest tests.test_ltc61_group_dispatch_uow_guard` — OK
  - `python3 -m unittest tests.test_ltc18_pipeline_busy_semantics` — OK
  - `python3 -m unittest tests.test_ltc42_group_runtime_use_cases` — OK
  - `python3 -m unittest tests.test_ltc44_uow_atomicity` — OK
  - `python3 -m unittest tests.test_ltc46_runtime_error_codes` — OK
  - `python3 -m unittest tests.test_ltc46_runtime_transitions_contract` — OK

## Risks / limitations
- В runtime ещё есть другие write-path, не входящие в scope LTC-61; они покрываются частично существующими guard-тестами.
- Инвариант “write only in UoW” для всего runtime требует дальнейшего пошагового расширения targeted guard-тестов за пределами group dispatch.
