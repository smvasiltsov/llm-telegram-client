# LTC-42: Выделение application-layer use-cases из Telegram handlers

## Что сделано
- Добавлен слой контрактов: `app/application/contracts/*`.
- Добавлены use-cases:
  - `app/application/use_cases/group_runtime.py`
  - `app/application/use_cases/private_pending_field.py`
  - `app/application/use_cases/callback_role_actions.py`
- Telegram handlers переведены в adapter-режим (без изменения внешнего поведения):
  - `app/handlers/messages_group.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/callbacks.py` (ветки `toggle_enabled/set_mode_*`)

## Контракты
- DTO (`dataclass`): `app/application/contracts/dto.py`
- Unified result/error: `app/application/contracts/result.py`
- Ports placeholders: `app/application/contracts/ports.py`

## Совместимость
- UX/тексты/callback_data сохранены.
- `commands/*` не изменялись.
- В `callbacks` добавлены snapshot/contract тесты на стабильность `callback_data`.

## Покрытие тестами
- Новые тесты:
  - `tests/test_ltc42_group_runtime_use_cases.py`
  - `tests/test_ltc42_private_pending_use_cases.py`
  - `tests/test_ltc42_callback_use_cases.py`
  - `tests/test_ltc42_callback_contract_snapshots.py`
- Прогнан расширенный regression-набор (включая pending/FIFO/master/team-role сценарии) — зелёный.

## Extension points / TODO
- `app/application/contracts/ports.py`:
  - TODO по введению transaction boundary / unit-of-work для multi-step use-cases.
- `callbacks.py`:
  - в application layer вынесены только приоритетные runtime-ветки (`toggle_enabled/set_mode_*`);
  - остальные ветки остаются кандидатом следующей итерации strangler-миграции.

## Ограничения текущего шага
- Полный transaction-boundary рефакторинг не выполнялся.
- Не добавлялся FastAPI transport слой (в рамках LTC-42 это вне scope).
