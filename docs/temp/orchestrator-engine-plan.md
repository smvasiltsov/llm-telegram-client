# Unified Conversation Engine Plan (Step 1)

## Цель
- Убрать расхождение поведения между `messages_group.py` и pending-flow в `messages_private.py`.
- Ввести единый pipeline обработки цепочки: `role -> orchestrator -> role`.

## Текущая проблема
- Логика оркестрации размазана по двум handlers и частично дублируется.
- Фиксы в одной ветке не всегда попадают во вторую (типовые регрессии: pending-flow vs group-flow).
- Антицикл, обработка missing user fields и post-event легко расходятся.

## Границы Unified Engine
- Engine отвечает только за бизнес-flow цепочки ролей:
  1. отправка запроса роли;
  2. обработка/отправка ответа в чат;
  3. post-event в оркестратор;
  4. делегации по `@role`;
  5. остановка цепочки.
- Telegram handlers отвечают только за адаптацию входа:
  - собрать `chat_id/user_id/text/reply/context`;
  - вызвать engine.

## Базовые инварианты (обязательно)
1. Поведение одинаково для group и pending group flow.
2. Для normal-role после ответа всегда выполняется post-event в orchestrator (если orchestrator активен).
3. Делегация по `@role` работает одинаково из ответа роли и ответа оркестратора.
4. Защита от петель единая:
   - аварийный лимит авто-цепочки `orchestrator_max_chain_auto_steps`;
   - лимит повторов одинакового делегирования `(source_role_id, target_role_id, normalized_text)` = 3;
   - self-target skip;
   - target orchestrator skip в role-delegation.
5. Ошибки обрабатываются едино:
   - `MissingUserField` -> pending + DM запрос;
   - 401 -> сброс auth + запрос токена;
   - 404 -> one-time session recovery.
6. Единая трассировка цепочки: каждый шаг логируется с `chain_id` и `hop`.

## Draft API (внутренний)
- `run_chain(...)`
  - вход: `chat_id`, `user_id`, `initial_roles`, `initial_text`, `reply_text`, `origin`.
  - выход: статус (`ok/partial/error`) + диагностический объект.
- `execute_role_request(...)`
- `send_role_response(...)`
- `send_orchestrator_post_event(...)`
- `dispatch_mentions(...)`

## Acceptance Criteria для шага 1
- Документ с границами и инвариантами зафиксирован в `docs/temp`.
- Термины и поведение синхронизированы с текущим JSON-контрактом в `docs/temp/orchestrator-json-schema.md`.

## Step 2 (выполнено)
- Добавлен базовый контракт контекста цепочки в код:
  - `app/services/role_pipeline.py`
  - `ChainContext` (`chain_id`, `hop`, `max_hops`, `reply_to_message_id`, `origin`, `visited_delegations`)
  - утилиты `can_continue()`, `next_hop()`, `delegation_key()`, `with_delegation()`
- Это подготовительный слой перед переносом runtime-логики handlers в unified engine.

## Step 3 (выполнено)
- Вынесен общий executor запроса в роль в сервис:
  - `app/services/role_pipeline.py`
  - `RoleRequestResult`
  - `resolve_role_model_override(...)`
  - `execute_role_request(...)`
- `messages_group.py` переключен на `execute_role_request(...)` (убраны локальные дубликаты executor-логики).
- pending-flow в `messages_private.py` также переключен на `execute_role_request(...)`.
- Эффект: один источник правды для payload/session/recovery логики в group и pending ветках.

## Step 4 (выполнено)
- Вынесен общий путь отправки ответа роли в чат:
  - `app/services/role_pipeline.py`
  - `send_role_response(...)`
- `messages_group.py` использует `send_role_response(..., apply_plugins=True)` для всех role/orchestrator ответов.
- pending-flow в `messages_private.py` использует `send_role_response(..., apply_plugins=False)` (без plugin pipeline, но через единый API).
- Эффект: единая точка для форматирования/отправки ответов и меньше расхождений между flow.

## Step 5 (выполнено)
- Вынесен post-event в orchestrator в сервис:
  - `app/services/role_pipeline.py`
  - `send_orchestrator_post_event(...)`
- `messages_group.py` переключен на вызов `send_orchestrator_post_event(...)` (локальный helper удален).
- Follow-up dispatch оркестратора передается через callback `dispatch_mentions`, чтобы сохранить текущую логику цепочек без дублирования кода.
- Эффект: единый post-event pipeline и меньше расхождений в ветках обработки.

## Step 6 (выполнено)
- Вынесен dispatcher делегаций в сервис:
  - `app/services/role_pipeline.py`
  - `extract_delegation_targets(...)`
  - `dispatch_mentions(...)`
- `messages_group.py` переведен на сервисный `dispatch_mentions(...)`, локальные `_extract_delegation_targets(...)` и `_dispatch_role_mentions_from_response(...)` удалены.
- pending-flow в `messages_private.py` также переведен на сервисный `dispatch_mentions(...)` (убрана зависимость от group-handler helper).
- Проверка синтаксиса пройдена:
  - `python3 -m py_compile app/services/role_pipeline.py app/handlers/messages_group.py app/handlers/messages_private.py`
- Эффект: единый источник правды для delegation-hop/dedup/anti-loop в group и pending цепочках.

## Step 7 (выполнено)
- Выполнена регрессия после унификации engine:
  - полная компиляция модулей `bot.py`, `app/*`, `app/handlers/*`, `app/services/*`, `app/tools/*`, `plugins/*`;
  - проверено, что `messages_group.py` и `messages_private.py` используют только сервисные entrypoints:
    - `execute_role_request(...)`
    - `send_orchestrator_post_event(...)`
    - `dispatch_mentions(...)`;
  - подтверждено удаление legacy helper-ов делегации из handlers.
- Зафиксирован отчет:
  - `docs/temp/step7-regression-report.md`
- Эффект: после шага 6 не осталось расхождения flow между group и pending ветками на уровне делегаций.

## Step 8 (выполнено)
- Добавлен единый orchestrator/role chain runner:
  - `app/services/role_pipeline.py`
  - `run_chain(...)`
  - `ChainRunResult`
- `run_chain(...)` объединяет общий цикл обработки ролей:
  - `execute_role_request(...)`
  - parse/fallback ответа orchestrator
  - `send_role_response(...)`
  - post-event в orchestrator (`send_orchestrator_post_event(...)`)
  - делегации (`dispatch_mentions(...)`)
  - единая обработка `MissingUserField`, `401`, `404-recovery notification`.
- `messages_group.py` переведен на `run_chain(...)` вместо локального цикла по ролям.
- pending-flow в `messages_private.py` также переведен на `run_chain(...)`.
- Проверка синтаксиса пройдена:
  - `python3 -m py_compile app/services/role_pipeline.py app/handlers/messages_group.py app/handlers/messages_private.py`
- Эффект: снято оставшееся дублирование цикла role/orchestrator chain между group и pending flow.

## Step 9 (выполнено)
- `ChainContext` интегрирован в runtime-поток делегаций (вместо набора примитивных параметров):
  - `dispatch_mentions(..., chain_context=ChainContext)`
  - `send_orchestrator_post_event(..., chain_context=ChainContext | None)`
- Логика anti-loop/dedup/hop-limit теперь идет через методы контекста:
  - `can_continue()`
  - `delegation_key(...)`
  - `same_delegation_count(...)`
  - `with_delegation(...).next_hop()`
- `run_chain(...)` создает базовый `ChainContext` на каждый role-response и использует его:
  - для post-event в orchestrator;
  - для direct delegation dispatch.
- Вызовы из handlers уточнены по origin:
  - `messages_group.py` -> `chain_origin="group"`
  - `messages_private.py` -> `chain_origin="pending"`
- Проверка синтаксиса пройдена:
  - `python3 -m py_compile app/services/role_pipeline.py app/handlers/messages_group.py app/handlers/messages_private.py`
- Эффект: цепочка делегаций типизирована одним объектом контекста, снижено число несогласованных параметров и риск регрессий при дальнейшем расширении.

## Step 10 (выполнено)
- Убран остаток дублирования pre-auth логики перед запуском chain:
  - `app/services/role_pipeline.py`:
    - добавлен helper `roles_require_auth(...)`
  - `messages_group.py` использует `roles_require_auth(...)` вместо локального цикла с `resolve_provider_model/role_requires_auth`.
  - `messages_private.py` использует `roles_require_auth(...)` в обоих местах:
    - при обработке входящего токена в DM;
    - при повторной обработке pending group-message.
- Проверка синтаксиса пройдена:
  - `python3 -m py_compile app/services/role_pipeline.py app/handlers/messages_group.py app/handlers/messages_private.py`
- Эффект: единая точка определения “требуется ли auth для набора ролей”, меньше риска рассинхронизации между group/pending/private ветками.

## Step 11 (выполнено)
- Обновлена стратегия антицикла в orchestration chain:
  - убран жесткий stop по `MAX_DELEGATION_HOPS = 2`;
  - добавлен аварийный лимит шагов цепочки из конфига: `orchestrator_max_chain_auto_steps` (по умолчанию `30`);
  - добавлен лимит повторов одинакового делегирования: `MAX_SAME_DELEGATION_REPEATS = 3`.
- Обновлен `ChainContext`:
  - история делегаций хранится как последовательность ключей делегирования;
  - проверка цикла идет по счетчику одинаковых ключей, а не по факту единственного совпадения.
- Эффект:
  - оркестратор может многократно делегировать в одну роль при разных текстах;
  - одинаковый auto-запрос режется только при повторе (3-й раз);
  - остается аварийный предохранитель длины цепочки.
