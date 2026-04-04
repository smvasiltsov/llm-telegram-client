# 01. Текущая доменная модель (as-is)

## 1. Цель и границы
- Цель: зафиксировать фактическую доменную модель системы (сущности, связи, жизненные циклы) как базу для API-миграции.
- Источники: только рабочий код `app/*` (без `docs/temp/*`).
- Модель ниже описывает текущее состояние хранения и runtime-оркестрации, которое уже используется Telegram-интерфейсом.

## 2. Сущности домена

### 2.1 Master role (базовая роль)
- Сущность: `Role` (`role_id`, `role_name`, `description`, `base_system_prompt`, `extra_instruction`, `llm_model`, `is_active`).
- Хранение: таблица `roles`.
- Факт применения master-полей через каталог: `Storage._apply_catalog_master_fields`.
- Источники:
  - `app/models.py:14`
  - `app/storage.py:161`
  - `app/storage.py:1907`
  - `app/storage.py:1944`

### 2.2 Team (команда)
- Сущность: `Team` (`team_id`, `public_id`, `name`, `is_active`, `ext_json`, timestamps).
- Хранение: таблица `teams`.
- Источники:
  - `app/models.py:50`
  - `app/storage.py:133`
  - `app/storage.py:1345`

### 2.3 Channel binding (привязка канала/интерфейса)
- Сущность: `TeamBinding` (`team_id`, `interface_type`, `external_id`, `external_title`, `is_active`).
- Хранение: таблица `team_bindings`.
- Для Telegram связь `chat_id <-> team_id` строится через `interface_type='telegram'`.
- Источники:
  - `app/models.py:61`
  - `app/storage.py:146`
  - `app/storage.py:1370`
  - `app/storage.py:1477`
  - `app/storage.py:1503`

### 2.4 Team role (роль в команде)
- Сущность: `TeamRole` (`team_id`, `role_id`, `team_role_id`, overrides, `enabled`, `mode`, `is_active`).
- Хранение: таблица `team_roles`.
- Семантика: master-role + team-level overrides (`system_prompt_override`, `extra_instruction_override`, `display_name`, `model_override`, suffix/prefix).
- Источники:
  - `app/models.py:72`
  - `app/storage.py:318`
  - `app/storage.py:2141`
  - `app/storage.py:2169`
  - `app/storage.py:3161`
  - `app/storage.py:3245`

### 2.5 Session (пользовательская сессия роли)
- Сущность: `UserRoleSession` (`telegram_user_id`, `team_id`, `role_id`, `team_role_id`, `session_id`, timestamps).
- Хранение: таблица `user_role_sessions`.
- Используется team/team_role-идентичность и backward-compatible путь.
- Источники:
  - `app/models.py:29`
  - `app/storage.py:174`
  - `app/storage.py:3461`
  - `app/storage.py:3524`

### 2.6 Messages (история сообщений)
- Сущность: `conversation_messages` (`session_id`, `role`, `content`, `created_at`).
- Хранение: таблица `conversation_messages`.
- Запись/чтение истории через `add_conversation_message`/`list_conversation_messages`.
- Источники:
  - `app/storage.py:203`
  - `app/storage.py:1617`
  - `app/storage.py:1629`

### 2.7 Ролевые параметры провайдера (user fields)
- Legacy role-scope: `provider_user_data (provider_id, key, role_id, value)`.
- Актуальный team-role-scope: `provider_user_data_team_role (provider_id, key, team_role_id, value)`.
- Блокировка fallback на legacy для конкретной `team_role_id`: `provider_user_data_team_role_legacy_blocks`.
- Источники:
  - `app/storage.py:214`
  - `app/storage.py:228`
  - `app/storage.py:242`
  - `app/storage.py:1688`
  - `app/storage.py:1722`
  - `app/storage.py:1782`

### 2.8 Skills и pre/post processing на уровне team-role
- Skills: `role_skills_enabled` + `RoleSkill`.
- Pre/Post: `role_prepost_processing` + `RolePrePostProcessing`.
- Семантика чтения/записи уже переведена на `team_role_id` (с fallback для старой схемы).
- Источники:
  - `app/models.py:141`
  - `app/models.py:153`
  - `app/storage.py:301`
  - `app/storage.py:284`
  - `app/storage.py:3752`
  - `app/storage.py:4115`
  - `app/storage.py:4192`

### 2.9 Runtime-состояние роли и блок-группы
- `TeamRoleRuntimeStatus`: статус `free/busy`, lease/heartbeat/release-delay, reason.
- Lock groups: `role_lock_groups`, `role_lock_group_members` для связанных блокировок.
- Источники:
  - `app/models.py:88`
  - `app/models.py:108`
  - `app/storage.py:362`
  - `app/storage.py:386`
  - `app/storage.py:398`
  - `app/services/role_runtime_status.py:52`

## 3. Связи и ER-уровень
- `teams (1) -> (N) team_bindings`
- `roles (1) -> (N) team_roles`
- `teams (1) -> (N) team_roles`
- `team_roles (1) -> (N) role_skills_enabled`
- `team_roles (1) -> (N) role_prepost_processing`
- `team_roles (1) -> (N) provider_user_data_team_role`
- `team_roles (1) -> (1) team_role_runtime_status`
- `users (1) -> (N) user_role_sessions`
- `auth_tokens` привязаны к `users` через `telegram_user_id`
- `conversation_messages (N)` связаны логически с `session_id` из `user_role_sessions`
- Источники:
  - `app/storage.py:133`
  - `app/storage.py:146`
  - `app/storage.py:161`
  - `app/storage.py:318`
  - `app/storage.py:301`
  - `app/storage.py:284`
  - `app/storage.py:228`
  - `app/storage.py:362`
  - `app/storage.py:174`
  - `app/storage.py:191`
  - `app/storage.py:203`

## 4. Runtime-состояния и жизненные циклы

### 4.1 Инициализация runtime-контекста
- В `build_runtime` собираются storage, router/executor, session resolver, runtime-status service, queue service, pending stores.
- Pending-хранилища очищаются на старте процесса.
- Источник: `app/app_factory.py:93`, `app/app_factory.py:104`, `app/app_factory.py:110`, `app/app_factory.py:112`, `app/app_factory.py:114`, `app/app_factory.py:176`.

### 4.2 Выполнение цепочки роли
- `run_chain`:
  - определяет target roles в команде,
  - получает `team_role_id`,
  - берёт FIFO-слот в очереди,
  - ждёт освобождения роли,
  - выполняет запрос,
  - при `MissingUserField` переводит в pending-flow.
- Источник: `app/services/role_pipeline.py:1250`, `app/services/role_pipeline.py:1291`, `app/services/role_pipeline.py:1315`, `app/services/role_pipeline.py:1333`, `app/services/role_pipeline.py:1392`.

### 4.3 Pending-flow для недостающих полей
- `_handle_missing_user_field` сохраняет:
  - pending исходного сообщения (`pending_messages`),
  - pending требуемого поля (`pending_user_fields`),
  - и отправляет prompt в ЛС.
- В private обработчике значение поля сохраняется в scoped storage и запускается replay pending-сообщения.
- Источники:
  - `app/handlers/messages_common.py:64`
  - `app/pending_store.py:28`
  - `app/pending_user_fields.py:18`
  - `app/handlers/messages_private.py:259`
  - `app/handlers/messages_private.py:282`
  - `app/handlers/messages_private.py:311`

### 4.4 Queue/Busy семантика
- Очередь исполнения по роли in-memory (`RoleDispatchQueueService`), FIFO через `deque`.
- Runtime `free/busy` с lease/release-delay в БД (`team_role_runtime_status`) через `RoleRuntimeStatusService`.
- Источники:
  - `app/services/role_dispatch_queue.py:31`
  - `app/services/role_dispatch_queue.py:45`
  - `app/services/role_dispatch_queue.py:77`
  - `app/services/role_runtime_status.py:98`
  - `app/services/role_runtime_status.py:120`
  - `app/storage.py:362`

## 5. Ограничения текущей модели (as-is)
- В storage и сервисах сохраняется слой legacy-совместимости (group-level facade + team-level core), что увеличивает ветвления в API-пути.
- Очередь исполнения по ролям реализована в памяти процесса (`RoleDispatchQueueService`), без персистентности между рестартами.
- Для части данных сохраняется dual-read/fallback логика (legacy role-scope vs team-role-scope).
- Источники:
  - `app/storage.py:3307`
  - `app/storage.py:3332`
  - `app/storage.py:1688`
  - `app/services/role_dispatch_queue.py:31`

## 6. Трассируемость (ключевые точки)
- Сущности: `app/models.py`.
- DDL/связи/операции: `app/storage.py`.
- Runtime orchestration: `app/services/role_pipeline.py`, `app/services/role_runtime_status.py`, `app/services/role_dispatch_queue.py`.
- Pending lifecycle: `app/handlers/messages_common.py`, `app/handlers/messages_private.py`, `app/pending_store.py`, `app/pending_user_fields.py`.
- Инициализация runtime-контейнера: `app/app_factory.py`.

### Подтверждение поведения по тестам
- Наследование master/team override: `tests/test_ltc13_inheritance_override.py:30`.
- Pending replay и release при `MissingUserField`: `tests/test_ltc18_pipeline_busy_semantics.py:347`.
- FIFO для одной роли (run_chain/dispatch/post-event): `tests/test_ltc18_pipeline_busy_semantics.py:560`, `tests/test_ltc18_pipeline_busy_semantics.py:656`, `tests/test_ltc18_pipeline_busy_semantics.py:1049`.
- Reset/remove->add и очистка team-scoped полей: `tests/test_core_team_roles_use_cases.py:83`, `tests/test_core_team_roles_use_cases.py:221`.
- Pending field retry-budget и подавление бесконечных prompt: `tests/test_root_dir_pending_flow.py:135`, `tests/test_root_dir_pending_flow.py:220`.
