# LTC-44: Транзакционные границы составных команд

## Scope
- `reset team-role session`
- `remove -> add` (в рамках `remove`-части текущего этапа)
- `session fields`
- `provider fields`

## Внедрённая UoW-модель
- Добавлен явный контекст `Storage.transaction(immediate: bool = False)`.
- Внешняя транзакция: `BEGIN`/`BEGIN IMMEDIATE` + `COMMIT`/`ROLLBACK`.
- Вложенные транзакции: `SAVEPOINT`/`ROLLBACK TO SAVEPOINT`/`RELEASE SAVEPOINT`.
- Логи: `tx_begin`, `tx_commit`, `tx_rollback`.

## Атомарные unit-of-work (реализовано)
- `reset_team_role_session_result(...)`: очистка session + team-scoped provider fields + legacy fallback blocks в одном transaction.
- `delete_team_role_binding_result(...)`: деактивация binding + очистка team-scoped данных + session + legacy fallback blocks в одном transaction.
- `upsert_user_role_session_result(...)`, `delete_user_role_session_result(...)`: атомарные операции session fields.
- `upsert_provider_field_by_team_role_result(...)`, `delete_provider_field_by_team_role_result(...)`: атомарные операции provider fields.

## Почему raw SQL в use-case
- Большинство текущих `Storage`-методов делают `commit()` внутри себя.
- Для строгой атомарности целевых сценариев внутри UoW использован raw SQL через один connection/cursor без промежуточных commit.

## Проверка
- Unit: `tests/test_ltc44_uow_atomicity.py`
  - commit/rollback/savepoint для `Storage.transaction`
  - rollback-инъекции с проверкой `no partial write` для 4 целевых сценариев
- Регрессии: `tests/test_core_team_roles_use_cases.py` + релевантные LTC-42/LTC-43 тесты.

## Ограничения и TODO
- Дополнительные пер-`team_role_id` lock-и не внедрялись (вне scope).
- Идемпотентность API-команд не расширялась (вне scope).
- Вне целевых сценариев остаются storage-пути с внутренними `commit()` (mixed-mode).
