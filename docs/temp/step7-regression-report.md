# Step 7 Regression Report

Дата: 2026-02-21 (обновлено)

## Что проверено автоматически
1. Компиляция Python-модулей:
   - `bot.py`
   - `app/*.py`
   - `app/handlers/*.py`
   - `app/services/*.py`
   - `app/tools/*.py`
   - `plugins/*.py`

2. Unified engine wiring после шага 6:
   - `messages_group.py` использует сервисные:
     - `execute_role_request(...)`
     - `send_orchestrator_post_event(...)`
     - `dispatch_mentions(...)`
   - pending-flow в `messages_private.py` использует те же сервисные entrypoints.

3. Делегации role->role и orchestrator->role:
   - локальные handler-дубликаты удалены;
   - единый dispatcher: `app/services/role_pipeline.py::dispatch_mentions(...)`;
   - единый extractor: `extract_delegation_targets(...)`.

4. Защита от циклов делегаций (актуально после последующих шагов):
   - аварийный лимит цепочки `orchestrator_max_chain_auto_steps` (config, default `30`);
   - лимит одинаковых делегаций по ключу `(source_role_id, target_role_id, normalized_text)` = 3 повтора;
   - `self-target` skip;
   - skip делегации в роль с `mode=orchestrator`.

5. Наблюдаемость:
   - логирование `delegation detected/sent/skip/failed`;
   - логирование `chain_id` и `hop` в цепочке делегаций;
   - логирование post-event в оркестратор.

6. Payload/actor контракт:
   - сбор через `build_llm_payload_json_text(...)`;
   - `llm_answer.role_name` заполняется при post-response в оркестратор.

## Найдено и исправлено в ходе шага 7
- Устаревшая зависимость pending-flow от group-helper делегаций.
- Исправление: `messages_private.py` переведен на `dispatch_mentions(...)` из `app/services/role_pipeline.py`.
- Удалены legacy-дубликаты делегации из `messages_group.py`.

## Что осталось проверить вручную (Telegram smoke)
1. Роль в ответе тегает другую роль (`@role`) -> целевая роль получает задачу и отвечает.
2. Оркестратор в ответе тегает роль -> роль получает задачу и отвечает.
3. Цепочка останавливается по `orchestrator_max_chain_auto_steps` без бесконечного зацикливания.
4. Повтор одинакового делегирования (same source->target + same text) блокируется на 3-м повторе.
5. Корректность actor/recipient в JSON payload:
   - user-origin = username пользователя;
   - role-origin = имя роли;
   - post-response в orchestrator = имя ответившей роли.
6. Recovery на 404 в делегированном сценарии (устаревший session_id у target role).
7. Сценарий 401 (auth reset) в делегированном вызове: запрос токена и отсутствие циклов.
