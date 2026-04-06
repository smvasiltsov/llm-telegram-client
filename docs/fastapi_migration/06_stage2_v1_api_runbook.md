# 06. Stage 2 v1 API Runbook (отдельно от Telegram)

## 1. Цель
- Запустить read-only API `/api/v1/*` как отдельный процесс interface adapter.
- Не менять Telegram UX и не включать write API.

## 2. Предпосылки
- Python 3.12+
- Актуальные зависимости:
  - `pip install -r requirements.txt`
- Конфиг и окружение:
  - `config.json` (или эквивалент с валидными путями/ключами)
  - доступ к `bot.sqlite3`

## 3. Быстрая проверка quality gates
- Перед запуском:
```bash
./scripts/stage2_read_api_gates.sh
```
- Ожидаемо: полный прогон зелёный.

## 4. Минимальный пример отдельного запуска API
- Вариант через `uvicorn` + фабрику приложения:
```bash
python3 -c "from pathlib import Path; from app.config import load_config, load_dotenv; from app.app_factory import build_runtime, build_read_only_api_application; cfg=load_config('config.json'); env=load_dotenv('.env'); rt=build_runtime(config=cfg, bot_username='', tools_bash_password=str(env.get('BASH_DANGEROUS_PASSWORD','')).strip(), providers_dir=Path('llm_providers'), plugins_dir=Path('plugins'), prepost_processing_dir=Path('prepost_processing'), skills_dir=Path('skills'), base_cwd=Path.cwd()); app=build_read_only_api_application(rt); import uvicorn; uvicorn.run(app, host='127.0.0.1', port=8080)"
```

## 5. Smoke-проверки
- `GET /api/v1/teams`:
```bash
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' http://127.0.0.1:8080/api/v1/teams
```
- Проверить:
  - статус `200`;
  - `X-Correlation-Id` в headers;
  - `items` + `meta` (pagination).

- Проверка authz:
```bash
curl -i http://127.0.0.1:8080/api/v1/teams
curl -i -H 'X-Owner-User-Id: 999999' http://127.0.0.1:8080/api/v1/teams
```
- Ожидаемо:
  - без owner header: `401`;
  - non-owner: `403`.

- Новые read-only endpoint-ы расширения:
```bash
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' 'http://127.0.0.1:8080/api/v1/roles/catalog?limit=20&offset=0'
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' 'http://127.0.0.1:8080/api/v1/roles/catalog?include_inactive=true'
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' http://127.0.0.1:8080/api/v1/roles/catalog/errors
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' http://127.0.0.1:8080/api/v1/teams/<TEAM_ID>/sessions
curl -i -H 'X-Owner-User-Id: <OWNER_ID>' 'http://127.0.0.1:8080/api/v1/teams/<TEAM_ID>/roles?include_inactive=true'
```
- Проверить:
  - `roles/catalog` по умолчанию возвращает только active роли;
  - при `include_inactive=true` возвращаются active + inactive;
  - `is_orchestrator` присутствует в `/roles/catalog` и `/teams/{team_id}/roles`;
  - `sessions` возвращает `items + meta` и поля `telegram_user_id`, `team_role_id`, `role_name`, `session_id`, `updated_at`.

## 6. Наблюдаемость
- Минимальные API-метрики:
  - `api_http_requests_total`
  - `api_http_request_latency_ms`
- Разрезы: `operation`, `result`, `transport=http`.

## 7. Ограничения и границы
- Scope v1:
  - `GET /api/v1/teams`
  - `GET /api/v1/teams/{team_id}/roles`
  - `GET /api/v1/teams/{team_id}/runtime-status`
  - `GET /api/v1/roles/catalog`
  - `GET /api/v1/roles/catalog/errors`
  - `GET /api/v1/teams/{team_id}/sessions`
- Out of scope:
  - write API;
  - rate limiting.
