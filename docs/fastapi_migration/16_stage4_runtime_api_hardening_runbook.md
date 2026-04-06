# 16. Stage 4 Runtime/API Hardening Runbook

Дата фиксации: **2026-04-05**

## 1. Цель
- Описать эксплуатационный контур Stage 4 для API/runtime hardening.
- Зафиксировать режимы запуска, мониторинг/алерты, инцидентные playbook и rollback.
- Сохранить обратную совместимость Telegram UX (изменений Telegram-пути не требуется).

## 2. Режимы запуска API/runtime

### 2.1 Standalone API (без Telegram процесса)
```bash
python3 -c "from pathlib import Path; from app.config import load_config, load_dotenv; from app.app_factory import build_runtime, build_read_only_api_application; cfg=load_config('config.json'); env=load_dotenv('.env'); rt=build_runtime(config=cfg, bot_username='', tools_bash_password=str(env.get('BASH_DANGEROUS_PASSWORD','')).strip(), providers_dir=Path('llm_providers'), plugins_dir=Path('plugins'), prepost_processing_dir=Path('prepost_processing'), skills_dir=Path('skills'), base_cwd=Path.cwd()); app=build_read_only_api_application(rt); import uvicorn; uvicorn.run(app, host='127.0.0.1', port=8080)"
```

### 2.2 Runtime dispatch режимы
- `single-instance`:
  - единственный runtime-инстанс;
  - dispatch/write разрешены.
- `single-runner`:
  - runner-инстанс: dispatch/write разрешены;
  - non-runner: dispatch/write запрещены (`409`, `runtime_non_runner_reject`);
  - read API доступен на runner и non-runner.

### 2.3 Операторский endpoint состояния runtime
- Endpoint: `GET /api/v1/runtime/dispatch-health`
- Ожидаемый payload:
```json
{
  "mode": "single-runner",
  "is_runner": false,
  "queue_backend": "in-memory",
  "started_at": "2026-04-05T00:00:00+00:00"
}
```

## 3. Monitoring и alerting (Stage 4)

### 3.1 Обязательные метрики
- `http_requests_total{method,route,status}`
- `http_request_duration_ms{method,route,status}`
- `runtime_operations_total{operation,result,error_code}`
- `runtime_queue_wait_ms{operation}`
- `runtime_busy_conflict_total{operation}`
- `runtime_pending_replay_total{result}`
- `runtime_inflight_operations{operation}`
- `runtime_queue_depth{queue_name}`

### 3.2 Базовые alert-триггеры
- API деградация:
  - рост `http_request_duration_ms` p95/p99 выше операционного порога;
  - рост доли `status=5xx`.
- Runtime contention:
  - устойчивый рост `runtime_busy_conflict_total`;
  - длительный ненулевой `runtime_queue_depth`.
- Pending replay:
  - рост `runtime_pending_replay_total{result=failed}`.
- Single-instance drift:
  - `single-runner` + критичный трафик на non-runner (`runtime_non_runner_reject` всплеск).

## 4. Инцидентные playbook

### 4.1 `busy-stuck`
- Симптомы:
  - роль долго в busy;
  - очередь не разгружается (`runtime_queue_depth` стабильно > 0).
- Проверки:
  - `GET /api/v1/teams/{team_id}/runtime-status`;
  - `GET /api/v1/runtime/dispatch-health`;
  - последние runtime-логи с `correlation_id`.
- Действия:
  - убедиться в здоровье runner;
  - выполнить контролируемый restart runtime-процесса;
  - повторно проверить queue-depth и runtime-status.

### 4.2 `queue reject` (`runtime_non_runner_reject`)
- Симптомы:
  - write/runtime запросы получают `409` с code `runtime_non_runner_reject`.
- Проверки:
  - `GET /api/v1/runtime/dispatch-health` (ожидаемо `is_runner=false`);
  - validate routing/load balancer на runner endpoint.
- Действия:
  - перенаправить write/runtime трафик на runner;
  - оставить read API на non-runner без изменений.

### 4.3 `pending replay failure`
- Симптомы:
  - рост `runtime_pending_replay_total{result=failed}`;
  - повторы replay без успешного завершения.
- Проверки:
  - логи runtime operation с `operation=runtime.pending_replay` и `correlation_id`;
  - проверка зависимостей LLM/provider и auth state.
- Действия:
  - стабилизировать upstream (token/provider);
  - повторить smoke на pending replay path;
  - при повторной деградации выполнить rollback.

## 5. Smoke/integration минимум перед release
- API standalone startup smoke.
- Read/write happy-path smoke.
- Authz smoke: `200/401/403`.
- Correlation-id propagation (`X-Correlation-Id` + `error.details.correlation_id`).
- Metrics emission sanity (все Stage 4 метрики).
- Single-instance reject scenario (`409/runtime_non_runner_reject`).
- Rollback drill (частичный fail + восстановление).
- CI gate:
  - script: `scripts/stage4_runtime_api_hardening_gates.sh`
  - workflow: `.github/workflows/stage4_runtime_api_hardening_gates.yml`

## 6. Rollback до предыдущего релиза
- Триггеры rollback:
  - критичные 5xx/latency деградации;
  - массовые queue/runtime rejects сверх допустимого окна;
  - непреодолимый pending replay failure.
- Процедура:
  1. Остановить выкладку и зафиксировать инцидент с `correlation_id` примерами.
  2. Переключить сервис на предыдущий стабильный артефакт/релиз.
  3. Проверить health endpoint и базовые smoke (`/teams`, write sample).
  4. Подтвердить восстановление метрик до baseline.
  5. Обновить postmortem и Stage 4 sign-off журнал.

## 7. Связанные документы
- `docs/fastapi_migration/15_stage4_runtime_api_hardening_checklist.md`
- `docs/fastapi_migration/04_migration_roadmap_and_risks.md`
- `docs/fastapi_migration/06_stage2_v1_api_runbook.md`
- `docs/fastapi_migration/12_stage3_v1_write_api_runbook.md`
