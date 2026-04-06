# 09. Stage 2 Read API Extension Checklist

Дата фиксации: **2026-04-05**

## 1. Цель
- Зафиксировать baseline и критерии приёмки для расширения Stage 2 read-only API.
- Обеспечить additive-only изменения v1 без breaking-контрактов.
- Подтвердить обязательные quality gates в `stage2_read_api_gates`.

## 2. Scope поставки
- Новые endpoint-ы:
  - `GET /api/v1/roles/catalog`
  - `GET /api/v1/roles/catalog/errors`
  - `GET /api/v1/teams/{team_id}/sessions`
- Расширения существующего read endpoint:
  - `GET /api/v1/teams/{team_id}/roles` -> добавить поле `is_orchestrator` (bool).
- Контракт фильтрации active/inactive:
  - default: только active;
  - query `include_inactive=true`: active + inactive.

## 3. Baseline (до реализации)
- Stage 1 sign-off: **GO**.
- Stage 2 v1 minimal scope: **GO** (`/teams`, `/teams/{team_id}/roles`, `/teams/{team_id}/runtime-status`).
- Merge gate: `stage2_read_api_gates` обязателен, OpenAPI snapshot блокирующий.
- Telegram UX: обратная совместимость обязательна; изменений поведения/текстов не планируется.

## 4. Обязательные acceptance criteria (blockers)

### B1. Endpoint contracts
- [x] `GET /api/v1/roles/catalog` возвращает `items[]` с минимум:
  - `role_name`, `is_active`, `llm_model`, `is_orchestrator`, `has_errors`, `source`;
  - `meta` с pagination.
- [x] `GET /api/v1/roles/catalog/errors` возвращает `errors[]`:
  - `role_name`, `file`, `code`, `message`, `details`.
- [x] `GET /api/v1/teams/{team_id}/sessions` возвращает:
  - `telegram_user_id`, `team_role_id`, `role_name`, `session_id`, `updated_at`;
  - pagination (`limit/offset` + `meta`).

### B2. Active/inactive filtering
- [x] В `roles` API применяется контракт:
  - default active-only;
  - `include_inactive=true` включает inactive роли.
- [x] Поведение согласовано между `/api/v1/roles/catalog` и `/api/v1/teams/{team_id}/roles`.

### B3. Orchestrator visibility
- [x] В `GET /api/v1/teams/{team_id}/roles` добавлено поле `is_orchestrator` (additive).
- [x] В `GET /api/v1/roles/catalog` добавлено поле `is_orchestrator` (additive).

### B4. Authz and error contract
- [x] Для всех новых endpoint-ов действует owner-only authz (`200/401/403`).
- [x] Сохраняется единый error envelope без ad-hoc форматов.

### B5. Additive-only compatibility
- [x] Нет breaking-изменений существующих DTO/response shape.
- [x] Новые поля/endpoint-ы добавляются только additive-путём в v1.

### B6. Tests (обязательные)
- [x] Contract/integration tests на 3 новых endpoint-а.
- [x] Тесты фильтра `include_inactive=true`.
- [x] Тесты `is_orchestrator` в `/teams/{team_id}/roles` и `/roles/catalog`.
- [x] Authz tests (`200/401/403`) для новых endpoint-ов.
- [x] DTO/response shape schema-contract tests.

### B7. CI gates
- [x] Обновлён blocking OpenAPI snapshot.
- [x] `stage2_read_api_gates` зелёный с новым тестовым набором.

### B8. Анализ расхождений UI/API
- [x] Зафиксирована причина расхождения active/inactive (UI vs API) и принятое API-решение.
- [x] Зафиксирована причина отсутствия orchestrator в API и принятое additive-решение.

## 5. Definition of Done
- Все блокеры B1-B8 закрыты.
- `stage2_read_api_gates` успешен.
- OpenAPI snapshot проходит как blocking check.
- Telegram UX не имеет регрессий.

Статус: **DONE (2026-04-05)**.

## 6. Исторический аудит baseline (до реализации этапов 3-5)
Ниже зафиксирован baseline на входе в реализацию: что уже было, чего не хватало и где требовались изменения.
Этот блок оставлен для traceability решений; итоговый статус закрытия зафиксирован в разделах 4, 5 и 8.

| Область | Что уже есть | Чего не хватает | Где реализовать (file:line) |
|---|---|---|---|
| Read router `/api/v1` | Есть только `GET /teams`, `GET /teams/{team_id}/roles`, `GET /teams/{team_id}/runtime-status`. | Нет `GET /roles/catalog`, `GET /roles/catalog/errors`, `GET /teams/{team_id}/sessions`. | `app/interfaces/api/routers/read_only_v1.py:89`, `app/interfaces/api/routers/read_only_v1.py:121`, `app/interfaces/api/routers/read_only_v1.py:150` |
| Use-cases read API | Есть use-cases только для teams/roles/runtime-status. | Нет use-cases для catalog, catalog errors, team sessions, include_inactive. | `app/application/use_cases/read_api.py:8`, `app/application/use_cases/read_api.py:20`, `app/application/use_cases/read_api.py:39` |
| DTO roles | Есть `RoleDTO` c базовыми полями (`role_name`, `is_active`, ...). | Нет `is_orchestrator`; нет DTO для role catalog item/errors/team sessions page. | `app/interfaces/api/schemas/entities.py:8` |
| Error envelope/authz | Единый error mapping и owner-only guard уже в read router. | Нужна привязка этого же контракта ко всем новым endpoint-ам. | `app/interfaces/api/routers/read_only_v1.py:64`, `app/interfaces/api/error_mapping.py:17` |
| Pagination/meta | Есть общий `ApiPagedResponse` и meta, используется в `/teams`. | Нужно применить pagination/meta к `/roles/catalog` и `/teams/{team_id}/sessions`. | `app/interfaces/api/schemas/common.py:23`, `app/interfaces/api/routers/read_only_v1.py:41`, `app/interfaces/api/routers/read_only_v1.py:119` |
| Data source: catalog | Runtime уже держит `role_catalog` (roles + issues). | Нет API-адаптера для выдачи ролей каталога и ошибок каталога в HTTP-контракте. | `app/runtime.py:83`, `app/role_catalog.py:31`, `app/role_catalog.py:96`, `app/role_catalog.py:34` |
| Data source: catalog domain mismatches | Есть механизм деактивации bindings при расхождении каталога и storage; есть `issues` по файлам. | Нет явной сборки и публикации domain mismatch ошибок в `/roles/catalog/errors`. | `app/role_catalog_service.py:135`, `app/role_catalog_service.py:138`, `app/role_catalog_service.py:143` |
| Data source: team sessions | Есть таблица `user_role_sessions` и операции get/save/touch для конкретного user/team_role. | Нет list API по `team_id` с `telegram_user_id, team_role_id, role_name, session_id, updated_at`. | `app/storage.py:3495`, `app/storage.py:3523`, `app/storage.py:3707` |
| include_inactive | В текущем API roles возвращаются из `list_roles_for_team` (active+enabled only). | Нет query `include_inactive`; нужен контракт default active-only + opt-in inactive. | `app/interfaces/api/routers/read_only_v1.py:131`, `app/application/use_cases/read_api.py:20`, `app/storage.py:2339`, `app/storage.py:2354` |
| is_orchestrator | В домене есть `mode` и lookup оркестратора; в Telegram UI это показывается. | В API roles нет `is_orchestrator`; нужно additive поле в `/teams/{team_id}/roles` и `/roles/catalog`. | `app/storage.py:2320`, `app/core/use_cases/team_roles.py:20`, `app/handlers/callbacks.py:414`, `app/interfaces/api/schemas/entities.py:8` |
| OpenAPI snapshot / CI | Snapshot test уже блокирующий и включает 3 текущих path. | Нужно расширить snapshot на новые path и новые схемы, обновить tests/gates. | `tests/test_ltc70_openapi_snapshot.py:67`, `tests/snapshots/read_only_openapi_snapshot.json:3`, `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:28` |

### 6.1 Ключевые расхождения UI/API (зафиксировано)
- Active/inactive:
  - Telegram UI в списке ролей опирается на `TeamRoleState.enabled` и показывает роли с `enabled=false` (OFF), если binding активен.
  - API `/teams/{team_id}/roles` сейчас берёт `storage.list_roles_for_team`, где фильтр `tr.enabled = 1`, поэтому disabled роли не попадают.
  - Подтверждение: `app/core/use_cases/team_roles.py:68`, `app/core/use_cases/team_roles.py:78`, `app/storage.py:2339`, `app/storage.py:2354`.
- Orchestrator:
  - Telegram UI использует `mode` (`orchestrator/normal`) в карточках/списках ролей.
  - API role DTO не содержит ни `mode`, ни `is_orchestrator`, поэтому признак теряется на HTTP-границе.
  - Подтверждение: `app/handlers/callbacks.py:414`, `app/handlers/callbacks.py:430`, `app/interfaces/api/schemas/entities.py:8`.

### 6.2 Точки внедрения (рекомендованный минимум)
- Router additions: `app/interfaces/api/routers/read_only_v1.py` (новые endpoint-ы + query `include_inactive` + pagination).
- Use-case additions: `app/application/use_cases/read_api.py` (catalog, catalog errors, team sessions, include_inactive policy).
- DTO/schema additions: `app/interfaces/api/schemas/entities.py` и при необходимости `operations.py` (новые DTO + additive поле `is_orchestrator`).
- Storage read methods: `app/storage.py` (list team sessions; role list variant с inactive opt-in без write side effects).
- Tests/contracts: `tests/test_ltc69_read_only_api_use_cases.py`, `tests/test_ltc69_read_only_fastapi_contract.py`, `tests/test_ltc70_openapi_snapshot.py`, `tests/snapshots/read_only_openapi_snapshot.json`.

## 7. Rationale решения (UI/API расхождения)
- Active/inactive:
  - Telegram UI остаётся операторским интерфейсом и должен показывать активные и отключенные роли для управления.
  - HTTP API остаётся read-only интеграционным интерфейсом; default active-only уменьшает шум для внешних клиентов.
  - Компромисс: `include_inactive=true` делает поведение явно управляемым и обратимо без breaking.
- `is_orchestrator`:
  - UI уже опирается на `mode=orchestrator`; отсутствие признака в API было информационным разрывом.
  - Добавлено additive поле `is_orchestrator` в `/teams/{team_id}/roles` и `/roles/catalog`, без изменения старых полей.
  - Поле `mode` пока не выносится в API, чтобы сохранить минимальный стабильный контракт v1.

## 8. Короткий sign-off по поставке
- Что сделано:
  - Реализованы новые endpoint-ы:
    - `GET /api/v1/roles/catalog`
    - `GET /api/v1/roles/catalog/errors`
    - `GET /api/v1/teams/{team_id}/sessions`
  - Расширен `GET /api/v1/teams/{team_id}/roles`:
    - `include_inactive=true`
    - `is_orchestrator`
  - Закрыты quality gates: контрактные тесты, authz `200/401/403`, единый error envelope, blocking OpenAPI snapshot, зелёный `stage2_read_api_gates`.
- Что вне scope:
  - write API;
  - rate limiting;
  - новые mutation-сценарии Telegram/HTTP.
- Остаточные риски:
  - Возможная неоднозначность интерпретации `is_active` для team-role (derived статус, не прямой флаг master-role).
  - Дальнейшее расширение API требует строгой дисциплины additive-only и обновления snapshot на каждую новую ручку/поле.
