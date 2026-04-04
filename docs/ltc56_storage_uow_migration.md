# LTC-56: Миграция Storage на внешнее управление транзакциями (UoW)

## Цель
Убрать mixed-mode транзакций в `Storage`: domain write-операции больше не делают внутренний `commit/rollback`; транзакционная граница задаётся снаружи через `Storage.transaction(...)`.

## Ключевые изменения
1. `Storage` переведён в sqlite autocommit-режим (`isolation_level=None`):
   - отдельные write-операции фиксируются немедленно;
   - атомарность составных сценариев обеспечивается только `BEGIN/COMMIT/ROLLBACK` в `Storage.transaction(...)`.
2. Введён runtime-guard:
   - `StorageTransactionRequiredError`;
   - `Storage.enable_write_uow_guard()`;
   - `_require_write_transaction(operation)` с логом `write_outside_transaction`.
3. Из domain write-методов удалены внутренние `self._conn.commit()` (и ad-hoc rollback).
4. На runtime-инициализации guard включается после bootstrap:
   - `reset_authorizations` выполняется в явном UoW;
   - затем `storage.enable_write_uow_guard()`.

## Разрешённые service boundary (внутренний commit допустим)
- `Storage.transaction(...)` (официальная UoW-граница)
- Schema/bootstrap/migration-пути (`_init_schema`, `_ensure_column`, `_migrate_*`)

## UoW-only domain write (инвариант)
Ниже перечислены write-методы, для которых теперь обязателен внешний `with storage.transaction(...):`

- `save_plugin_text`
- `log_tool_run`
- `log_skill_run`
- `upsert_user`
- `upsert_team`
- `upsert_team_binding`
- `set_telegram_team_binding_active`
- `add_conversation_message`
- `block_provider_user_legacy_fallback`
- `unblock_provider_user_legacy_fallback`
- `set_provider_user_value`
- `delete_provider_user_value`
- `set_provider_user_value_by_team_role`
- `delete_provider_user_value_by_team_role`
- `delete_all_provider_user_values_by_team_role`
- `set_user_authorized`
- `upsert_auth_token`
- `reset_authorizations`
- `upsert_role`
- `ensure_team_role`
- `bind_master_role_to_team`
- `ensure_team_role_runtime_status`
- `update_team_role_runtime_preview`
- `mark_team_role_runtime_busy`
- `mark_team_role_runtime_free`
- `mark_team_role_runtime_release_requested`
- `finalize_due_team_role_runtime_releases`
- `heartbeat_team_role_runtime_status`
- `create_role_lock_group`
- `set_role_lock_group_active`
- `add_team_role_to_lock_group`
- `remove_team_role_from_lock_group`
- `cleanup_stale_busy_team_roles`
- `set_team_role_prompt`
- `set_team_role_display_name`
- `set_team_role_model`
- `set_team_role_extra_instruction`
- `set_team_role_user_prompt_suffix`
- `set_team_role_user_reply_prefix`
- `set_team_role_enabled`
- `set_team_role_mode`
- `deactivate_team_role`
- `deactivate_team_roles_by_role_name`
- `update_role_name`
- `delete_role_if_unused`
- `save_user_role_session_by_team`
- `save_user_role_session_by_team_role`
- `delete_user_role_session_by_team`
- `delete_user_role_session_by_team_role`
- `touch_user_role_session_by_team`
- `touch_user_role_session_by_team_role`
- `upsert_role_prepost_processing_for_team_role`
- `set_role_prepost_processing_enabled_for_team_role`
- `set_role_prepost_processing_config_for_team_role`
- `delete_role_prepost_processing_for_team_role`
- `upsert_role_skill_for_team_role`
- `set_role_skill_enabled_for_team_role`
- `set_role_skill_config_for_team_role`
- `delete_role_skill_for_team_role`

## Совместимость
- Telegram UX/тексты/callback_data не менялись.
- Для legacy use-case путей добавлены явные UoW-обёртки (в `team_roles`), чтобы поведение осталось прежним.

## Тестовое подтверждение
- Контракт guard: `tests/test_ltc56_storage_uow_guard.py`
- Atomicity/UoW: `tests/test_ltc44_uow_atomicity.py`
- Regression use-cases/handlers/error model:
  - `tests/test_core_team_roles_use_cases.py`
  - `tests/test_ltc43_error_model.py`
  - `tests/test_ltc43_error_contracts.py`
  - `tests/test_ltc42_callback_use_cases.py`
  - `tests/test_ltc42_group_runtime_use_cases.py`
  - `tests/test_ltc42_private_pending_use_cases.py`

## TODO / ограничения
1. Вне целевого scope могут оставаться call-sites, где write выполняется без явного UoW до включения guard в конкретном окружении.
2. Дополнительные lock/idempotency-улучшения не внедрялись (out of scope LTC-56).
3. Для FastAPI-слоя рекомендуется включать guard во всех entrypoints и формализовать UoW-per-command как обязательный контракт.
