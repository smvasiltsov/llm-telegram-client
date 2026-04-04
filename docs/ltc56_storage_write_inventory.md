# LTC-56 Step 1: Инвентаризация write-path в Storage

Источник: `app/storage.py` (поиск `self._conn.commit()/rollback()` и SQL write-операций).

## Сводка
- Найдено методов с внутренней фиксацией транзакции: `70`.
- Service boundary (допустимо оставить): `10`.
- Domain write (перевести на внешний UoW): `60`.

## Service boundary (оставляем автокоммит в LTC-56)
- `transaction` (явный UoW boundary)
- `_ensure_column`
- `_init_schema`
- `_migrate_provider_user_data_team_role_additive`
- `_migrate_role_runtime_status_additive`
- `_migrate_role_name_bindings_additive`
- `_migrate_team_role_surrogate_additive`
- `_migrate_teams_additive`
- `_migrate_to_team_only_schema`
- `_migrate_role_prepost_processing`

## Domain write (кандидаты на удаление внутренних commit/rollback)
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
- `try_acquire_team_role_busy`
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

## Результат шага
- Полный список и классификация зафиксированы.
- На шаге 2 вводим runtime-guard и общий helper для UoW-only write-методов.
