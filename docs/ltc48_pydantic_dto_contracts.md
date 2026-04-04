# LTC-48: Сериализуемые DTO-контракты для API boundary

## Scope

В рамках LTC-48 добавлены Pydantic v2 схемы на границе `application/interface` без удаления текущих внутренних `dataclass`.

Базовый пакет схем:
- `app/interfaces/api/schemas/common.py`
- `app/interfaces/api/schemas/entities.py`
- `app/interfaces/api/schemas/operations.py`
- `app/interfaces/api/schemas/adapters.py`

## Матрица `domain -> DTO -> operations`

| Domain entity | DTO | Основные operation-модели |
|---|---|---|
| `Role` | `RoleDTO` | `ListRequestDTO`, `GetRequestDTO` |
| `Team` | `TeamDTO` | `ListRequestDTO`, `GetRequestDTO` |
| `TeamBinding` | `TeamBindingDTO` | `ListRequestDTO`, `GetRequestDTO` |
| `TeamRole` | `TeamRoleDTO` | `GetRequestDTO`, `UpdateRequestDTO`, `OperationResultDTO` |
| `UserRoleSession` | `UserRoleSessionDTO` | `ResetRequestDTO`, `DeleteRequestDTO`, `OperationResultDTO` |
| `TeamRoleRuntimeStatus` | `TeamRoleRuntimeStatusDTO` | `GetRequestDTO`, `OperationResultDTO` |

## Operation contract (первая волна)

Request:
- `ListRequestDTO`
- `GetRequestDTO`
- `UpdateRequestDTO`
- `ResetRequestDTO`
- `DeleteRequestDTO`

Response:
- `OperationResultDTO` (`ok/message` + опциональные `team_role/session/runtime_status`)

Параметры для use-case/store-слоя формируются через адаптеры:
- `list_request_to_params`
- `get_request_to_params`
- `update_request_to_patch`
- `reset_request_to_params`
- `delete_request_to_params`

Результаты use-case слоя (`Result`) маппятся в API shape через:
- `operation_result_to_dto`

## Миграционные правила (mixed-mode)

1. `dataclass` модели домена остаются внутренним контрактом runtime/use-case.
2. Pydantic DTO используются на API boundary и в новых transport-ready адаптерах.
3. Массовый перевод всех handler/use-case путей не выполняется в LTC-48.
4. Новые endpoint-ы должны принимать/возвращать только схемы из `app/interfaces/api/schemas/*`.
5. Error-контракт остаётся из LTC-43 (`Result/AppError`), без расширения envelope в LTC-48.

## Инварианты схем

1. Pydantic v2 (`BaseModel`, `ConfigDict`, `from_attributes=True`).
2. Минимальная безопасная валидация: типы, nullability, очевидные enum (`mode`, `status`).
3. JSON shape фиксируется контракт-тестами LTC-48.

## Ограничения и TODO

1. В текущем окружении тестов нужна установка `pydantic` в runtime/venv, иначе DTO-тесты выполняются как `skipped`.
2. Версионирование API namespace (`v1`) вынесено в следующий этап.
3. Единый response envelope (например, `data/error/meta`) вне scope LTC-48.
