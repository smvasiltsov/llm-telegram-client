# 08. Инвентаризация Telegram-операций для Stage 2+ планирования

## 1. Цель и границы
Цель документа: зафиксировать полный инвентарь **реально доступных** пользователю Telegram-операций и разложить их по stage API-миграции.

Границы анализа (source of truth):
- `app/handlers`
- `app/application`
- `app/core/use_cases`
- `app/interfaces/runtime`
- `app/interfaces/api`
- `app/runtime.py`
- `tests/*`
- `docs/fastapi_migration/*`

## 2. Baseline (на старт инвентаризации)
- Stage 1 sign-off завершён; Stage 2 v1 read-only adapter введён в эксплуатационный контур проекта.
- Stage 2 v1 scope в HTTP уже зафиксирован тремя endpoint-ами:
  - `GET /api/v1/teams`
  - `GET /api/v1/teams/{team_id}/roles`
  - `GET /api/v1/teams/{team_id}/runtime-status`
- Для Stage 2 v1 действует обязательный merge gate `stage2_read_api_gates`, включая blocking OpenAPI snapshot.

## 3. Таксономия операций (для инвентаризации)
Каждая операция в инвентаре будет фиксироваться как запись с полями:
- `Intent`: пользовательская цель (user-intent, язык продукта).
- `Telegram Entry`: как пользователь попадает в сценарий (команда/кнопка/ветка меню).
- `Key Sub-operations`: ключевые подоперации внутри сценария (без низкоуровневого callback-шумa).
- `Read/Write Profile`: характер доступа к состоянию:
  - `READ` — только чтение;
  - `WRITE` — изменение доменных данных/состояния;
  - `ORCHESTRATION` — многошаговый сценарий с переходами состояния и/или побочными эффектами.
- `Stage Candidate`:
  - `Stage 2` — только READ-кандидаты в HTTP;
  - `Stage 3+` — WRITE/ORCHESTRATION и зависимые от них сценарии.
- `Traceability`: подтверждающие ссылки `file:line` (код + тесты при наличии).

## 4. Критерии включения и исключения
### 4.1 Включаем в инвентарь
- Только сценарии, которые реально достижимы для пользователя через Telegram UX (команды/кнопки/ветки).
- Операции на уровне user-intent с ключевыми подоперациями.
- Сценарии, подтверждённые кодом и/или тестами.

### 4.2 Исключаем из инвентаря
- Мёртвый/недостижимый код без реального пользовательского entrypoint.
- Внутренние низкоуровневые callback-детали, не образующие отдельный user-intent.
- Черновые/экспериментальные артефакты вне runtime-контура.

## 5. Правила stage-разбивки
- В Stage 2 попадают только READ-операции, которые можно представить как стабильный HTTP GET-контракт без изменения Telegram UX.
- WRITE/mutation/оркестрационные сценарии относятся к Stage 3+.
- Если операция содержит смешанный профиль (read + mutation), она маркируется Stage 3+ до выделения чистого read-only среза.

## 6. Метод traceability
- Для каждого кандидата Stage 2 GET обязательна ссылка `file:line` на кодовый источник факта.
- Для ключевых тезисов/рисков также даются `file:line`.
- Полный реестр ссылок для каждой строки кода не требуется.

## 7. Критерии готовности результата (для следующих этапов)
На выходе полной инвентаризации (этапы 2+):
- Полный список Telegram-операций с stage-классификацией.
- Отдельный consolidated список всех GET-кандидатов Stage 2.
- Краткая оценка готовности GET-набора Stage 2 (`x/10`) и вердикт `go/no-go`.

## 8. Начальная трассируемость baseline
- Stage 2 v1 sign-off и scope: `docs/fastapi_migration/07_stage2_v1_signoff.md:5`, `docs/fastapi_migration/07_stage2_v1_signoff.md:13`.
- Обязательный gate и блокирующий характер: `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:27`, `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:92`.
- Общий scope набора документов и source-of-truth: `docs/fastapi_migration/README.md:4`, `docs/fastapi_migration/README.md:13`.

## 9. Полный инвентарь реально доступных Telegram user-intent операций (этап 2)
Ниже перечислены операции, которые реально доступны через зарегистрированные Telegram entrypoints (команды, callback-кнопки, message-ветки).

| ID | Intent | Telegram Entry | Key Sub-operations | Read/Write Profile | Stage Candidate | Traceability |
|---|---|---|---|---|---|---|
| OP-01 | Просмотреть список групп | `/groups` (private) | Загрузка активных Telegram-групп, построение inline-списка выбора группы | READ | Stage 2 (read-only) | `app/interfaces/telegram/adapter.py:76`, `app/handlers/commands.py:83`, `app/handlers/commands.py:91` |
| OP-02 | Просмотреть каталог master-role | `/roles` (private) | Сбор master-role view, вывод списка ролей и CTA на создание | READ | Stage 2 (read-only) | `app/interfaces/telegram/adapter.py:77`, `app/handlers/commands.py:53`, `app/handlers/commands.py:61`, `app/handlers/commands.py:76` |
| OP-03 | Просмотреть роли выбранной группы | `grp:{group_id}` callback и `/group_roles <group_id>` | Построение списка ролей группы со статусами и переходом в карточку роли | READ | Stage 2 (read-only) | `app/handlers/callbacks.py:530`, `app/handlers/callbacks.py:533`, `app/handlers/commands.py:105`, `app/interfaces/telegram/adapter.py:81` |
| OP-04 | Открыть карточку роли группы | `role:{group_id}:{role_id}` callback | Вывод runtime/state карточки роли и меню действий | READ | Stage 2 (read-only) | `app/handlers/callbacks.py:554`, `app/handlers/callbacks.py:561`, `app/handlers/callbacks.py:564` |
| OP-05 | Добавить master-role в группу | `addrole:{group_id}` -> `addrole_master_name:{group_id}:{role_name}` | Выбор роли из master-role списка и привязка к группе | WRITE | Stage 3+ | `app/handlers/callbacks.py:681`, `app/handlers/callbacks.py:702`, `app/handlers/callbacks.py:705` |
| OP-06 | Создать новую master-role | `mrole_create` + private follow-up | Пошаговый wizard: имя -> prompt -> instruction -> выбор модели -> создание JSON роли | ORCHESTRATION | Stage 3+ | `app/handlers/callbacks.py:267`, `app/handlers/messages_private.py:510`, `app/handlers/messages_private.py:523`, `app/handlers/callbacks.py:377` |
| OP-07 | Просмотреть карточку master-role и привязки | `mrole_name:{role_name}` | Карточка master-role, отображение привязок к командам, навигация к добавлению | READ | Stage 2 (read-only) | `app/handlers/callbacks.py:280`, `app/handlers/callbacks.py:215`, `app/handlers/callbacks.py:233`, `app/handlers/callbacks.py:297` |
| OP-08 | Привязать master-role к выбранной группе из карточки | `mrole_add_name:{role_name}` -> `mrole_bind_name:{role_name}:{group_id}` | Выбор группы, привязка роли, возврат в карточку | WRITE | Stage 3+ | `app/handlers/callbacks.py:304`, `app/handlers/callbacks.py:316`, `app/handlers/callbacks.py:332`, `app/handlers/callbacks.py:335` |
| OP-09 | Переключить состояние роли (enabled/mode) | `act:toggle_enabled`, `act:set_mode_orchestrator`, `act:set_mode_normal` | Обновление enable/mode и повторный рендер карточки роли | WRITE | Stage 3+ | `app/handlers/callbacks.py:739`, `app/handlers/callbacks.py:784`, `app/handlers/callbacks.py:833`, `tests/test_ltc42_callback_contract_snapshots.py:99` |
| OP-10 | Управлять системным prompt роли | `act:set_prompt`, `act:clear_prompt`, `/role_set_prompt` | Ввод/очистка role prompt через private ветку или command path | WRITE | Stage 3+ | `app/handlers/callbacks.py:874`, `app/handlers/callbacks.py:1044`, `app/handlers/messages_private.py:756`, `app/handlers/commands.py:157`, `app/interfaces/telegram/adapter.py:82` |
| OP-11 | Управлять инструкциями роли (suffix/reply_prefix) | `act:set_suffix`, `act:clear_suffix`, `act:set_reply_prefix`, `act:clear_reply_prefix` | Запрос значения в private, сохранение/очистка user prompt suffix и reply prefix | WRITE | Stage 3+ | `app/handlers/callbacks.py:1112`, `app/handlers/callbacks.py:1141`, `app/handlers/callbacks.py:1151`, `app/handlers/callbacks.py:1180`, `app/handlers/messages_private.py:632`, `app/handlers/messages_private.py:645` |
| OP-12 | Управлять LLM-моделью team-role | `act:set_model` -> `setmodel:{group_id}:{role_id}:{model}` | Выбор модели из provider map и сохранение override | WRITE | Stage 3+ | `app/handlers/callbacks.py:1070`, `app/handlers/callbacks.py:1331`, `app/handlers/callbacks.py:1345` |
| OP-13 | Управлять master defaults (prompt/instruction/model) | `act:master_defaults` и дочерние `act:master_*`, `msetmodel:*` | Просмотр defaults, установка/очистка prompt/instruction/model master-role | WRITE | Stage 3+ | `app/handlers/callbacks.py:895`, `app/handlers/callbacks.py:902`, `app/handlers/callbacks.py:967`, `app/handlers/callbacks.py:988`, `app/handlers/callbacks.py:1009`, `app/handlers/callbacks.py:1290`, `tests/test_ltc42_callback_contract_snapshots.py:123` |
| OP-14 | Переименовать роль, сбросить сессию, удалить роль из группы | `act:rename_role`, `act:reset_session`, `act:delete_role`, `/role_reset_session` | Rename display name, reset role session, deactivate/delete team-role binding | WRITE | Stage 3+ | `app/handlers/callbacks.py:1054`, `app/handlers/callbacks.py:1190`, `app/handlers/callbacks.py:1197`, `app/handlers/commands.py:196`, `app/interfaces/telegram/adapter.py:83` |
| OP-15 | Управлять skills роли | `act:skills` -> `sktoggle:{group_id}:{role_id}:{skill_id}` | Просмотр skill-списка роли и включение/выключение skill | WRITE | Stage 3+ | `app/handlers/callbacks.py:1037`, `app/handlers/callbacks.py:1245`, `app/handlers/callbacks.py:1256`, `tests/test_ltc66_callbacks_skill_toggle_uow_guard.py:136` |
| OP-16 | Управлять pre/post-processing роли | `act:prepost_processing` -> `pptoggle:{group_id}:{role_id}:{id}` | Просмотр pre/post списка и переключение enabled состояния | WRITE | Stage 3+ | `app/handlers/callbacks.py:1030`, `app/handlers/callbacks.py:1207`, `app/handlers/callbacks.py:1230` |
| OP-17 | Управлять lock groups роли | `act:lock_groups`, `lockg:create`, `lockg:add`, `lockg:remove` | Просмотр lock groups, создание новой группы, добавление/удаление связей | WRITE | Stage 3+ | `app/handlers/callbacks.py:577`, `app/handlers/callbacks.py:637`, `app/handlers/callbacks.py:644`, `app/handlers/callbacks.py:658`, `app/handlers/callbacks.py:671` |
| OP-18 | Просмотреть инструменты и запускать bash-команду владельцем | `/tools`, `/bash` (private) + password branch | Просмотр реестра tools, попытка bash, запрос/проверка пароля, выполнение/отмена | ORCHESTRATION | Stage 3+ | `app/interfaces/telegram/adapter.py:78`, `app/interfaces/telegram/adapter.py:80`, `app/handlers/commands.py:237`, `app/handlers/commands.py:260`, `app/handlers/messages_private.py:249`, `app/handlers/messages_private.py:307` |
| OP-19 | Отправить групповой запрос на роль/оркестратор | Group text branch (non-command) | Буферизация, routing по `@role/@all` или orchestrator, `dispatch_chain`, при необходимости запрос токена | ORCHESTRATION | Stage 3+ | `app/interfaces/telegram/adapter.py:88`, `app/handlers/messages_group.py:55`, `app/handlers/messages_group.py:161`, `app/application/use_cases/group_runtime.py:152`, `app/application/use_cases/group_runtime.py:205`, `tests/test_ltc42_group_runtime_use_cases.py:190` |
| OP-20 | Завершить pending-flow в личке (токен/поле провайдера) и replay | Private text branch | Валидация и сохранение токена/required user field, попытка `pending replay` и очистка pending state | ORCHESTRATION | Stage 3+ | `app/handlers/messages_private.py:659`, `app/handlers/messages_private.py:703`, `app/handlers/messages_private.py:341`, `app/handlers/messages_private.py:875`, `app/application/use_cases/private_pending_replay.py:31`, `tests/test_ltc42_private_pending_use_cases.py:216` |

## 10. Что намеренно исключено из user-intent инвентаря
- Системные lifecycle-события (не пользовательские intent-операции): автосинхронизация привязки команды при `my_chat_member` и `group_seen`.
- Причина исключения: это не команды/кнопки/ветки взаимодействия пользователя, а внутренние runtime hooks.
- Traceability: `app/handlers/membership.py:15`, `app/handlers/membership.py:34`, `app/interfaces/telegram/adapter.py:85`, `app/interfaces/telegram/adapter.py:86`.

## 11. Traceability-верификация (tests/docs) и корректировки инвентаря
### 11.1 Что подтверждено явно
- Контракт callback-меню содержит ветки `skills`, `prepost_processing`, `lock_groups`, `rename/reset/delete`: `tests/test_ltc42_callback_contract_snapshots.py:95`, `tests/test_ltc42_callback_contract_snapshots.py:108`.
- Поведение toggle role action подтверждено use-case/smoke тестами: `tests/test_ltc42_callback_use_cases.py:102`, `tests/test_ltc42_callback_use_cases.py:153`.
- Skill toggle path подтверждён транзакционными и UX smoke тестами: `tests/test_ltc66_callbacks_skill_toggle_uow_guard.py:123`, `tests/test_ltc66_callbacks_skill_toggle_uow_guard.py:164`.
- Group dispatch и auth/pending ветки подтверждены use-case тестами: `tests/test_ltc42_group_runtime_use_cases.py:190`, `tests/test_ltc42_group_runtime_use_cases.py:214`.
- Private pending replay подтверждён отдельным use-case набором: `tests/test_ltc42_private_pending_replay_use_case.py:68`, `tests/test_ltc42_private_pending_replay_use_case.py:91`.

### 11.2 Спорные/слабо покрытые зоны
- Для `/groups`, `/roles`, `/tools`, `/bash` нет отдельного полного handler-level contract набора; подтверждение в основном через регистрацию и частичные смежные тесты.
- Для `lock_groups` и `prepost_processing` в тестах доминирует контракт callback-data; поведенческого e2e-покрытия веток `lockg:*`/`pptoggle:*` мало.
- Для master-role wizard (`mrole_create` и шаги private-диалога) есть частичные проверки (`master_defaults_flow`), но нет полного happy-path e2e сценария создания и последующей привязки.
- Для `/group_roles` есть контракт ошибки not-found, но ограниченное покрытие позитивного end-to-end path.

### 11.3 Корректировки после верификации
- Исправлено несоответствие структуры: в таблицу добавлен обязательный столбец `Stage Candidate` (раньше отсутствовал).
- Stage-разметка операций выровнена с текущими docs (`04`, `05`, `07`): Stage 2 = read-only, write/orchestration = Stage 3+.
- Системные lifecycle hooks (`membership`) подтверждены как вне user-intent scope и оставлены в исключениях.

### 11.4 Ссылки на docs-консистентность stage-границ
- Roadmap по stage-границам: `docs/fastapi_migration/04_migration_roadmap_and_risks.md:30`, `docs/fastapi_migration/04_migration_roadmap_and_risks.md:48`.
- Stage 2 v1 фактический scope и out-of-scope: `docs/fastapi_migration/07_stage2_v1_signoff.md:13`, `docs/fastapi_migration/07_stage2_v1_signoff.md:25`.
- Чеклист Stage 2 entry и write API вне текущего окна: `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:18`, `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:19`.

## 12. Разложение операций по stage (этап 4)
### 12.1 Stage 2: read-only HTTP кандидаты
- OP-01 `Просмотреть список групп`.
  - Обоснование: read-only список сущностей команды/группы, без мутаций; естественно маппится на list endpoint.
  - Traceability: `app/handlers/commands.py:83`, `app/handlers/commands.py:91`, `app/interfaces/telegram/adapter.py:76`.
- OP-02 `Просмотреть каталог master-role`.
  - Обоснование: чистое чтение каталога master-role и агрегированного view, без state change.
  - Traceability: `app/handlers/commands.py:53`, `app/handlers/commands.py:61`, `app/interfaces/telegram/adapter.py:77`.
- OP-03 `Просмотреть роли выбранной группы`.
  - Обоснование: read-only выборка ролей команды; уже частично реализовано в Stage 2 v1 (`GET /api/v1/teams/{team_id}/roles`).
  - Traceability: `app/handlers/commands.py:105`, `app/handlers/commands.py:121`, `docs/fastapi_migration/07_stage2_v1_signoff.md:15`.
- OP-04 `Открыть карточку роли группы`.
  - Обоснование: отображение статуса/метаданных роли без изменения состояния; read-only карточечный view.
  - Traceability: `app/handlers/callbacks.py:554`, `app/handlers/callbacks.py:561`, `app/handlers/callbacks.py:564`.
- OP-07 `Просмотреть карточку master-role и привязки`.
  - Обоснование: read-only просмотр master-role и связей team-role bindings; подходит для read API расширения.
  - Traceability: `app/handlers/callbacks.py:280`, `app/handlers/callbacks.py:224`, `app/handlers/callbacks.py:233`.

### 12.2 Stage 3+: write/mutation/оркестрации
- OP-05, OP-08: привязка ролей к группам (write binding).
- OP-06: мастер-role creation wizard (multi-step orchestration + write).
- OP-09..OP-17: изменение состояния ролей/моделей/skills/prepost/lock groups (write mutations).
- OP-18: privileged tooling/bash flow (orchestration + side effects).
- OP-19, OP-20: runtime dispatch и pending replay (orchestration с runtime transitions/side effects).

## 13. Полный список GET-операций для Stage 2 (consolidated)
Ниже перечислены все read-only операции из текущего Telegram UX, которые можно реализовать в рамках Stage 2 как HTTP GET.

### GET-01. Список команд/групп
- Telegram intent: OP-01 `Просмотреть список групп`.
- HTTP-кандидат: `GET /api/v1/teams` (уже реализован в Stage 2 v1) + возможное расширение полей.
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: строгий v1-контракт списка (`extra=forbid`, pagination/meta).
  - data source: team bindings/teams из storage.
- Traceability: `app/handlers/commands.py:83`, `app/handlers/commands.py:91`, `docs/fastapi_migration/07_stage2_v1_signoff.md:14`.

### GET-02. Список ролей команды
- Telegram intent: OP-03 `Просмотреть роли выбранной группы`.
- HTTP-кандидат: `GET /api/v1/teams/{team_id}/roles` (уже реализован в Stage 2 v1).
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: строгий v1-контракт списка ролей команды.
  - data source: team_roles + roles в storage/use-case `read_api`.
- Traceability: `app/handlers/commands.py:121`, `app/handlers/callbacks.py:533`, `docs/fastapi_migration/07_stage2_v1_signoff.md:15`.

### GET-03. Runtime-статусы ролей команды
- Telegram intent: часть OP-04 `Открыть карточку роли группы` (runtime/state view).
- HTTP-кандидат: `GET /api/v1/teams/{team_id}/runtime-status` (уже реализован в Stage 2 v1).
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: строгий v1-контракт runtime status rows.
  - data source: team_role_runtime_status + runtime status service.
- Traceability: `app/handlers/callbacks.py:561`, `docs/fastapi_migration/07_stage2_v1_signoff.md:16`, `tests/test_ltc69_read_only_fastapi_contract.py:97`.

### GET-04. Карточка team-role (детальный read-view)
- Telegram intent: OP-04 `Открыть карточку роли группы`.
- HTTP-кандидат: `GET /api/v1/teams/{team_id}/roles/{role_id}` (расширение Stage 2 read-only).
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: отдельный strict DTO карточки (state + runtime preview).
  - data source: team_role state + runtime preview/status из storage.
- Traceability: `app/handlers/callbacks.py:554`, `app/handlers/callbacks.py:564`.

### GET-05. Карточка master-role с привязками
- Telegram intent: OP-07 `Просмотреть карточку master-role и привязки`.
- HTTP-кандидат: `GET /api/v1/master-roles/{role_name}` (или `/api/v1/master-roles/{role_id}`) как read-only расширение Stage 2.
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: strict DTO master-role card + bindings (active_only).
  - data source: role catalog + bindings (`list_team_role_bindings_for_role`) из storage.
- Traceability: `app/handlers/callbacks.py:215`, `app/handlers/callbacks.py:224`, `app/handlers/callbacks.py:233`.

### GET-06. Список master-role
- Telegram intent: OP-02 `Просмотреть каталог master-role`.
- HTTP-кандидат: `GET /api/v1/master-roles` (read-only расширение Stage 2).
- Ограничения/зависимости:
  - authz: owner-only (`200/401/403`).
  - DTO: строгий список master-role (name, model, health/flags по контракту).
  - data source: role catalog service + identities из storage.
- Traceability: `app/handlers/commands.py:53`, `app/handlers/commands.py:61`, `app/handlers/callbacks.py:190`.

## 14. Итоговая оценка готовности GET-набора Stage 2
- Оценка готовности: **8.9/10**.
- Вердикт: **GO** для реализации полного GET-набора Stage 2 (с учётом ограничений ниже).

### 14.1 Почему GO
- Базовый read-only каркас и обязательный минимальный scope уже стабилизированы (`GET /teams`, `GET /teams/{team_id}/roles`, `GET /teams/{team_id}/runtime-status`): `docs/fastapi_migration/07_stage2_v1_signoff.md:13`.
- Stage 2 gate-контур и blocking OpenAPI snapshot уже приняты в процессе поставки: `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:27`, `docs/fastapi_migration/05_stage2_entry_execution_checklist.md:28`.
- Ключевые read-intent операции имеют прямую трассируемость к текущему Telegram UX и storage/use-case источникам (разделы 12.1 и 13).

### 14.2 Краткие риски
- Неполное handler-level покрытие для части read-кандидатов (`/groups`, `/roles`, карточки master-role) может замедлить стабилизацию DTO edge-cases.
- Для расширенных read endpoint-ов (карточки role/master-role) нужен аккуратный контракт полей preview/runtime, чтобы избежать дрейфа между Telegram view и API DTO.
- Owner-only authz достаточен для текущего scope, но остаётся эксплуатационным ограничением при дальнейшем расширении read surface.

### 14.3 Допущения
- Сохраняется текущий принцип Stage 2: только read-only HTTP, без write/mutation/оркестраций.
- Для всех новых GET endpoint-ов применяются те же transport-политики Stage 2 v1: owner-only authz, единый error envelope, strict DTO/OpenAPI contract.
- Telegram UX остаётся неизменным; API добавляется как параллельный interface adapter без влияния на существующий Telegram-путь.
