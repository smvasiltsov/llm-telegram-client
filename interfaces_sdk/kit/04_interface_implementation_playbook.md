# Interface Implementation Playbook

## Вариант A: внешний интерфейс через HTTP API (рекомендуется)

1. Реализуй клиент API с обязательными headers.
2. Поддержи выбор `team_id` и `team_role_id` из `GET /teams` + `GET /teams/{team_id}/roles`.
3. Отправляй вопрос в `POST /questions` с `origin_interface=<your_interface_id>`.
4. Доставляй ответы:
- либо polling `/questions/{id}/answer`
- либо через Event Bus подписки.
5. Обрабатывай validation ошибки (особенно missing required team role fields).

## Вариант B: встроенный runtime adapter

Контракт см. `interfaces_sdk/contract.py`.

Нужно реализовать:

- `create_adapter(core_port, runtime, config)`
- объект с `interface_id`, `start()`, `stop()`

Стартовый шаблон:

- `interfaces_sdk/template_adapter.py`

Проверка контракта:

```bash
python3 -m scripts.interface_sdk_smoke <your_module_path> <your_interface_id>
```

## Минимальный сценарий отправки question

1. Получить `team_role_id`.
2. Сформировать payload:

```json
{
  "team_id": 3,
  "team_role_id": 12,
  "text": "Запрос",
  "origin_interface": "my-ui",
  "origin_type": "user"
}
```

3. Отправить с `Idempotency-Key`.
4. Сохранить `question_id` и `thread_id` локально для трекинга.

## Обязательные edge cases

- 409 на `/questions/{id}/answer` означает ответ еще не готов.
- `validation.invalid_input` с `missing_required_team_role_fields`:
  интерфейс должен попросить пользователя заполнить `working_dir`/`root_dir` и повторить отправку.
- Не создавать новый question при retry клиента: использовать тот же `Idempotency-Key`.

## Совместимость

- Не полагаться на legacy telegram pipeline.
- Опираться на `/api/v1` и event bus admin endpoints.
- Не использовать внутренние таблицы БД напрямую из интерфейса.
