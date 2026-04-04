# LTC-43: Unified Error Model

## Scope
- Внедрён единый error model в application-layer.
- Добавлен transport mapping слой (Telegram now, FastAPI-ready payload).
- Охват: ветки `LTC-42` + точечные источники (`storage.py:1998`, `storage.py:2209`, `handlers/commands.py:109`).

## Error Contract
- Поля ошибки:
  - `code: str`
  - `message: str`
  - `details: dict[str, Any] | None`
  - `http_status: int`
  - `retryable: bool`
- Реализация:
  - `app/application/contracts/result.py`
  - `app/application/contracts/errors.py`

## Error Codes Registry
- `storage.not_found` -> `404`
- `validation.invalid_input` -> `422`
- `auth.unauthorized` -> `401`
- `conflict.already_exists` -> `409`
- `internal.unexpected` -> `500`

## Mapping Rules
- Центральный mapper: `map_exception_to_error(...)`.
- Спец-кейсы ValueError:
  - `Role not found: ...` -> `storage.not_found`
  - `Team role not found: ...` -> `storage.not_found`
  - `Telegram group binding not found: ...` -> `storage.not_found`
- Остальные `ValueError` -> `validation.invalid_input`.
- Unexpected exceptions -> `internal.unexpected`.

## Transport Mapping
- `to_api_error_payload(error)` — FastAPI-ready структура ошибки.
- `to_telegram_message(error, fallback)` — сохраняет UX-тексты Telegram (fallback остаётся прежним).
- `log_structured_error(...)` — structured logging с `error_code/http_status/details/retryable`.

## Affected Files
- Contracts:
  - `app/application/contracts/errors.py`
  - `app/application/contracts/result.py`
  - `app/application/contracts/error_transport.py`
- Use-cases:
  - `app/application/use_cases/group_runtime.py`
  - `app/application/use_cases/private_pending_field.py`
  - `app/application/use_cases/callback_role_actions.py`
  - `app/application/use_cases/storage_access.py`
- Handlers:
  - `app/handlers/messages_group.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/callbacks.py`
  - `app/handlers/commands.py`

## Compatibility
- Telegram пользовательские тексты сохранены.
- `callback_data` контракт не менялся.
- `commands/*` UX не менялся; добавлены только structured-логи и внутренняя нормализация ошибок.

## Mixed Mode / TODO
- Mixed-mode сохраняется вне затронутого scope (`ValueError` ещё есть в неохваченных частях `app/*`).
- Следующий шаг: расширить mapper/typed errors на remaining handlers/use-cases и подготовить прямой FastAPI exception middleware.
