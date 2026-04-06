# 12. Stage 3 v1 Write API Runbook

## 1. Цель
- Запустить и проверить Stage 3 v1 write API в `/api/v1`.
- Подтвердить owner-only authz, idempotency и единый error envelope.
- Сохранить полную обратную совместимость Telegram UX.

## 2. Предпосылки
- Python 3.12+
- Установлены зависимости:
```bash
pip install -r requirements.txt
```
- Доступен рабочий `config.json` и `bot.sqlite3`.

## 3. Обязательный pre-flight
- Перед ручной проверкой:
```bash
./scripts/stage3_write_api_gates.sh
```
- Ожидаемо: полный прогон зелёный.

## 4. Запуск API отдельно от Telegram
```bash
python3 -c "from pathlib import Path; from app.config import load_config, load_dotenv; from app.app_factory import build_runtime, build_read_only_api_application; cfg=load_config('config.json'); env=load_dotenv('.env'); rt=build_runtime(config=cfg, bot_username='', tools_bash_password=str(env.get('BASH_DANGEROUS_PASSWORD','')).strip(), providers_dir=Path('llm_providers'), plugins_dir=Path('plugins'), prepost_processing_dir=Path('prepost_processing'), skills_dir=Path('skills'), base_cwd=Path.cwd()); app=build_read_only_api_application(rt); import uvicorn; uvicorn.run(app, host='127.0.0.1', port=8080)"
```

## 5. Smoke-проверки write endpoints
- PATCH team-role:
```bash
curl -i -X PATCH \
  -H 'X-Owner-User-Id: <OWNER_ID>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"display_name":"Dev"}' \
  http://127.0.0.1:8080/api/v1/teams/<TEAM_ID>/roles/<ROLE_ID>
```

- POST reset-session (idempotent):
```bash
curl -i -X POST \
  -H 'X-Owner-User-Id: <OWNER_ID>' \
  -H 'Idempotency-Key: reset-001' \
  -H 'Content-Type: application/json' \
  -d '{"telegram_user_id":123456789}' \
  http://127.0.0.1:8080/api/v1/teams/<TEAM_ID>/roles/<ROLE_ID>/reset-session
```

- DELETE deactivate binding (idempotent):
```bash
curl -i -X DELETE \
  -H 'X-Owner-User-Id: <OWNER_ID>' \
  -H 'Idempotency-Key: deact-001' \
  -H 'Content-Type: application/json' \
  -d '{"telegram_user_id":123456789}' \
  http://127.0.0.1:8080/api/v1/teams/<TEAM_ID>/roles/<ROLE_ID>
```

- PUT skill toggle/config:
```bash
curl -i -X PUT \
  -H 'X-Owner-User-Id: <OWNER_ID>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"config":{"root_dir":"/tmp"}}' \
  http://127.0.0.1:8080/api/v1/team-roles/<TEAM_ROLE_ID>/skills/<SKILL_ID>
```

- PUT prepost toggle/config:
```bash
curl -i -X PUT \
  -H 'X-Owner-User-Id: <OWNER_ID>' \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"config":{"x":1}}' \
  http://127.0.0.1:8080/api/v1/team-roles/<TEAM_ROLE_ID>/prepost/<PREPOST_ID>
```

## 6. Контрольные ожидания
- Authz:
  - без owner header -> `401`;
  - non-owner -> `403`.
- Успех:
  - `PATCH/POST/PUT` -> `200`;
  - `DELETE` -> `204`.
- Ошибки:
  - `404` not found;
  - `409` conflict;
  - `422` validation/invariant.
- Формат ошибки: единый envelope `{"error":{...}}`.

## 7. Idempotency semantics (операционные правила)
- `Idempotency-Key` обязателен для `POST reset-session` и `DELETE deactivate`.
- Повтор с тем же ключом и тем же payload:
  - без повторной побочной мутации.
- Повтор с тем же ключом и другим payload:
  - `422 validation.invalid_input`.

## 8. Transaction boundaries (операционные правила)
- Границы UoW обязательны и проверяются тестами для:
  - reset session;
  - deactivate binding;
  - skill toggle;
  - prepost toggle/config-lite;
  - runtime status transitions (когда затрагиваются).

## 9. Границы и ограничения
- Stage 3 v1 scope: только endpoints из `docs/fastapi_migration/10_stage3_write_api_execution_checklist.md`.
- Out of scope:
  - async queue API (`202`);
  - compensating workflows;
  - расширенная authz-модель beyond owner-only;
  - rate limiting.
