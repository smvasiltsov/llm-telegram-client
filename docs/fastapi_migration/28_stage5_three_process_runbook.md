# 28. Stage 5 Three-Process Runbook (`runtime + api + telegram`)

## 1) Конфиг (обязательно)
```bash
cd /opt/llm/llm-telegram-client-in-dev
cp config.json /tmp/config.stage5.3proc.backup.json
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("config.json")
cfg = json.loads(p.read_text(encoding="utf-8"))
cfg.setdefault("interface", {}).setdefault("telegram", {})
cfg["interface"]["telegram"]["api_base_url"] = "http://127.0.0.1:8080"
cfg["interface"]["telegram"]["api_timeout_sec"] = 30
cfg["interface"]["telegram"]["thin_client_enabled"] = True
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("telegram config:", cfg["interface"]["telegram"])
PY
```
Ожидаемо: выведены `api_base_url=http://127.0.0.1:8080`, `api_timeout_sec=30`, `thin_client_enabled=True`.

## 2) Запуск 3 процессов
```bash
cd /opt/llm/llm-telegram-client-in-dev
source .venv/bin/activate

python3 runtime_service.py
```
```bash
cd /opt/llm/llm-telegram-client-in-dev
source .venv/bin/activate

python3 api_service.py
```
```bash
cd /opt/llm/llm-telegram-client-in-dev
source .venv/bin/activate

python3 telegram_service.py
```
Ожидаемо:
- `runtime_service.py`: `starting runtime service host=127.0.0.1 port=8091`;
- `api_service.py`: `starting api service host=127.0.0.1 port=8080`;
- `telegram_service.py`: `starting telegram service ... thin=True api_base_url=http://127.0.0.1:8080`.

## 3) Health-check runtime/api
```bash
curl -i http://127.0.0.1:8091/health/live
curl -i http://127.0.0.1:8091/health/ready
curl -i http://127.0.0.1:8080/openapi.json
```
Ожидаемо:
- `runtime /health/live` -> `200`;
- `runtime /health/ready` -> `200` и `status=ready`;
- `api /openapi.json` -> `200`.

## 4) HTTP smoke: terminal flow
```bash
OWNER_ID=$(python3 - <<'PY'
import json
print(json.load(open("config.json", "r", encoding="utf-8"))["owner_user_id"])
PY
)

TEAM_ID=$(curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/teams?limit=1&offset=0" | python3 - <<'PY'
import json,sys
data=json.load(sys.stdin)
items=data.get("items") or []
print(items[0]["team_id"] if items else "")
PY
)

TEAM_ROLE_ID=$(curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID}/roles?include_inactive=false" | python3 - <<'PY'
import json,sys
items=json.load(sys.stdin) or []
print(items[0]["team_role_id"] if items else "")
PY
)

REQ=$(curl -sS -X POST "http://127.0.0.1:8080/api/v1/questions" \
  -H "Content-Type: application/json" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Idempotency-Key: manual-smoke-$(date +%s)" \
  -d "{\"team_id\": ${TEAM_ID}, \"team_role_id\": ${TEAM_ROLE_ID}, \"text\": \"stage5 3proc smoke\"}")
echo "$REQ"
QID=$(echo "$REQ" | python3 - <<'PY'
import json,sys
print((json.load(sys.stdin).get("question") or {}).get("question_id",""))
PY
)

for _ in $(seq 1 60); do
  S=$(curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/questions/${QID}/status")
  ST=$(echo "$S" | python3 - <<'PY'
import json,sys
print(json.load(sys.stdin).get("status",""))
PY
)
  echo "status=${ST}"
  case "$ST" in answered|failed|timeout|cancelled) echo "$S"; break;; esac
  sleep 2
done
```
Ожидаемо: вопрос уходит в terminal (`answered`/`failed`/`timeout`/`cancelled`) не остаётся навсегда в `accepted`.

## 5) HTTP smoke: `working_dir` / `root_dir`
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/working-dir" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"working_dir":"/tmp/work"}'

curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/root-dir" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"root_dir":"/tmp/root"}'

curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" \
  "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID}/roles?include_inactive=false" | python3 - <<'PY'
import json,sys
items=json.load(sys.stdin) or []
first=items[0] if items else {}
print({
  "team_role_id": first.get("team_role_id"),
  "working_dir": first.get("working_dir"),
  "root_dir": first.get("root_dir"),
})
PY
```
Ожидаемо:
- оба `PUT` возвращают `200`;
- в `GET /teams/{team_id}/roles` у роли видны `working_dir` и `root_dir`.

## 5.1) HTTP smoke: create master-role / create team
```bash
NEW_ROLE=$(curl -sS -X POST "http://127.0.0.1:8080/api/v1/roles" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"role_name":"smoke_master_role","system_prompt":"You are smoke role","llm_model":"gpt-4o-mini","description":"Smoke","extra_instructions":"Reply short"}')
echo "$NEW_ROLE"

NEW_TEAM=$(curl -sS -X POST "http://127.0.0.1:8080/api/v1/teams" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Team"}')
echo "$NEW_TEAM"
```
Ожидаемо:
- оба `POST` возвращают `201`;
- у роли `is_active=true`;
- у команды `public_id` начинается с `team-`.

Проверка дубля роли (`409`):
```bash
curl -i -X POST "http://127.0.0.1:8080/api/v1/roles" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"role_name":"smoke_master_role","system_prompt":"dup","llm_model":"gpt-4o-mini"}'
```
Ожидаемо: `409` и `error.code=conflict.already_exists`.

## 5.2) HTTP smoke: rename/delete team, delete master-role
Переименовать команду (`200`):
```bash
TEAM_ID_TO_RENAME=$(python3 - <<'PY'
import json,sys
payload=json.loads(sys.stdin.read() or "{}")
print(payload.get("team_id",""))
PY
<<< "$NEW_TEAM")

curl -i -X PATCH "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID_TO_RENAME}" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Team Renamed"}'
```

Удалить пустую команду (`204`):
```bash
curl -i -X DELETE "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID_TO_RENAME}" \
  -H "X-Owner-User-Id: ${OWNER_ID}"
```

Удалить неиспользуемую мастер-роль (`204`):
```bash
ROLE_ID_TO_DELETE=$(python3 - <<'PY'
import json,sys
payload=json.loads(sys.stdin.read() or "{}")
print(payload.get("role_id",""))
PY
<<< "$NEW_ROLE")

curl -i -X DELETE "http://127.0.0.1:8080/api/v1/roles/${ROLE_ID_TO_DELETE}" \
  -H "X-Owner-User-Id: ${OWNER_ID}"
```

Проверка конфликтов (`409`):
```bash
# team in use
curl -i -X DELETE "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID}" \
  -H "X-Owner-User-Id: ${OWNER_ID}"

# role in use (привязана в team_roles)
curl -i -X DELETE "http://127.0.0.1:8080/api/v1/roles/$(python3 - <<'PY'
import json,sys
items=json.load(sys.stdin) or []
print(items[0].get("role_id","") if items else "")
PY
<<< "$(curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" "http://127.0.0.1:8080/api/v1/teams/${TEAM_ID}/roles?include_inactive=true")")" \
  -H "X-Owner-User-Id: ${OWNER_ID}"
```

## 5.3) HTTP smoke: bulk replace skills/prepost
Полная замена skills (`200`):
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/skills" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"skill_id":"fs.list_dir","enabled":true,"config":{"root_dir":"/tmp"}},{"skill_id":"fs.read_file","enabled":false,"config":{"x":1}}]}'
```

Очистка skills через `items: []` (`200`):
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/skills" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"items":[]}'
```

Полная замена prepost (`200`):
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/prepost" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"prepost_id":"echo","enabled":true,"config":{"x":1}},{"prepost_id":"trim","enabled":false,"config":{"y":2}}]}'
```

Очистка prepost через `items: []` (`200`):
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/team-roles/${TEAM_ROLE_ID}/prepost" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d '{"items":[]}'
```

Проверки ошибок:
- duplicate `skill_id`/`prepost_id` в одном payload -> `422`.
- неизвестный `skill_id`/`prepost_id` -> `404`.

## 6) Telegram smoke: message -> answer
Действия:
- Написать боту в Telegram личное сообщение (owner-user).
- Для group-сценария отправить сообщение с role-tag.

Проверка:
- в логе `telegram_service.py`: `private msg correlation_id=...` или `group msg correlation_id=...`;
- в логе `api_service.py`: `api_request_started`/`api_request_finished` для `/api/v1/questions` и polling `/answer`;
- в Telegram появляется ответ (или контролируемый terminal error без зависания).

## 7) Telegram thin DM-сбор и авто-продолжение
Сценарий `working_dir`:
- Использовать team-role, где `working_dir` ещё не задан (например, новая роль/команда).
- Отправить боту запрос на роль с провайдером, требующим `working_dir`.
- Если поле отсутствует, бот пишет в личку запрос `working_dir`.
- Ответить в ЛС абсолютным путём, например `/tmp/work`.
- Ожидаемо: бот сам продолжает исходный запрос и возвращает итог без повторной отправки сообщения.

Сценарий `root_dir`:
- Убедиться, что у роли есть включённый навык `fs.*`.
- Очистить/не задавать `root_dir` (для новой роли поле пустое по умолчанию).
- Отправить запрос на эту роль.
- Ожидаемо: бот в ЛС просит `root_dir`; после ответа абсолютным путём (например `/tmp/root`) исходный запрос продолжается автоматически.

## 7.1) Event Bus / Outbox admin smoke
```bash
curl -i -X PUT "http://127.0.0.1:8080/api/v1/admin/event-subscriptions" \
  -H "X-Owner-User-Id: ${OWNER_ID}" \
  -H "Content-Type: application/json" \
  -d "{\"scope\":\"team\",\"scope_id\":\"${TEAM_ID}\",\"interface_type\":\"mirror\",\"target_id\":\"team-${TEAM_ID}\",\"is_active\":true}"

curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" \
  "http://127.0.0.1:8080/api/v1/admin/thread-events?team_id=${TEAM_ID}&limit=10"

curl -sS -H "X-Owner-User-Id: ${OWNER_ID}" \
  "http://127.0.0.1:8080/api/v1/admin/event-deliveries/summary"
```
Ожидаемо:
- subscription создаётся (`200`);
- есть `thread.message.created` события;
- summary возвращает `failed_dlq/avg_lag_ms/max_lag_ms`.

## 8) Fallback (legacy path)
```bash
python3 - <<'PY'
import json, pathlib
p=pathlib.Path("config.json")
cfg=json.loads(p.read_text(encoding="utf-8"))
cfg.setdefault("interface", {}).setdefault("telegram", {})["thin_client_enabled"]=False
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("thin_client_enabled=", cfg["interface"]["telegram"]["thin_client_enabled"])
PY
```
Перезапустить только `telegram_service.py`.  
Ожидаемо: обработка идёт по legacy path.

## 9) Остановка и откат конфига
В терминалах сервисов: `Ctrl+C`.

```bash
cd /opt/llm/llm-telegram-client-in-dev
cp /tmp/config.stage5.3proc.backup.json config.json
```
Ожидаемо: процессы остановлены, конфиг восстановлен.

## 10) Rollout checklist
1. Обновить код `api_service` + `runtime_service`.
2. Перезапустить процессы (`runtime`, затем `api`, затем `telegram`).
3. Прогнать smoke:
   - `POST /api/v1/roles` -> `201`;
   - `POST /api/v1/teams` -> `201`;
   - `PATCH /api/v1/teams/{team_id}` -> `200`;
   - `DELETE /api/v1/teams/{team_id}` (empty) -> `204`;
   - `DELETE /api/v1/roles/{role_id}` (unused) -> `204`;
   - `DELETE /api/v1/teams/{team_id}` (in use) -> `409`;
   - `DELETE /api/v1/roles/{role_id}` (in use) -> `409`;
   - `PUT /api/v1/team-roles/{team_role_id}/skills` (full replace) -> `200`;
   - `PUT /api/v1/team-roles/{team_role_id}/skills` (`items: []`) -> `200` + пустой список;
   - `PUT /api/v1/team-roles/{team_role_id}/prepost` (full replace) -> `200`;
   - `PUT /api/v1/team-roles/{team_role_id}/prepost` (`items: []`) -> `200` + пустой список;
   - duplicate ids в bulk payload -> `422`;
   - unknown ids в bulk payload -> `404`;
   - duplicate `role_name` -> `409`;
   - invalid payload -> `422`.
4. Проверить authz:
   - без `X-Owner-User-Id` -> `401`;
   - с чужим `X-Owner-User-Id` -> `403`.
5. Проверить `/openapi.json` доступность и новые маршруты.
6. Откат (если нужно):
   - вернуть предыдущий релиз;
   - перезапустить `runtime/api/telegram`;
   - перепроверить smoke по старому baseline.
