# 25. Stage Runtime Extraction — Этап 4 (Runtime Service Process)

## Статус
- `Этап 4`: `DONE` (DoD выполнен).

## Checklist (DoD)
- Отдельный runtime service entrypoint (старт/стоп независимо от public API): `DONE`.
- Startup/shutdown lifecycle для bridge worker в runtime service: `DONE`.
- Health/readiness endpoints для runtime service: `DONE`.
- Operator controls endpoint для runtime dispatch health (owner-only): `DONE`.
- Подтверждение smoke/integration тестами: `DONE`.

## Реализация
- `runtime_service.py`
- `app/interfaces/runtime/runtime_service_app.py`
- `app/interfaces/api/qa_dispatch_bridge_worker.py` (`snapshot` для operator endpoint)

## Подтверждение тестами
- `tests/test_ltc84_runtime_service_process_smoke.py`
- Обновлён gate: `scripts/stage4_runtime_api_hardening_gates.sh` (включён `tests.test_ltc84_runtime_service_process_smoke`)

## Примечание по текущему окружению
- В локальном sandbox smoke/integration тесты FastAPI могут быть `skipped` при отсутствии `fastapi/pydantic`; в CI с полным окружением они входят в обязательный stage4 gate.
