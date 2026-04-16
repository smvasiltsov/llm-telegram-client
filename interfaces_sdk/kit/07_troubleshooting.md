# Troubleshooting

## Симптом: question accepted, но интерфейс не получил ответ

Проверь по шагам:

1. `GET /questions/{id}/status`
- если `in_progress|queued`, обработка еще идет.
- если `failed|timeout`, смотри `error_code/error_message`.

2. `GET /admin/thread-events?thread_id=...`
- есть ли событие ответа (`direction=answer`).

3. `GET /admin/event-deliveries?event_id=...`
- есть ли доставка на нужный `interface_type/target_id`.

4. `GET /admin/event-subscriptions`
- не пусты ли подписки для вашего scope.

## Симптом: события есть, но идут не в тот интерфейс

Причина: у question `origin_interface` выставлен не ваш interface id.

Проверка:

- смотреть `origin_interface` в `thread-events`.

Фикс:

- отправлять `POST /questions` с корректным `origin_interface`.

## Симптом: validation error на create question

Ошибка типа:

- `Missing required team role fields: working_dir, root_dir...`

Действия:

1. Прочитать `missing_fields` в `error.details`.
2. Вызвать:
- `PUT /team-roles/{team_role_id}/working-dir`
- `PUT /team-roles/{team_role_id}/root-dir`
3. Повторить `POST /questions` с новым idempotency key.

## Симптом: дубли в интерфейсе

Проверь:

- не работает ли одновременно legacy delivery и event bus delivery;
- не создается ли более одной подписки на тот же target;
- не дублирует ли интерфейс обработку одного `event_id`.

Рекомендация:

- сохранять локально обработанные `event_id` и игнорировать повтор.

## Симптом: reset role отдает ok, но фактически не сбросил

Проверь:

- корректность `team_role_id`;
- корректность `telegram_user_id` (для reset endpoint);
- что состояние роли читается из `GET /teams/{team_id}/roles` после reset.

## Быстрый check-list

- Есть `X-Owner-User-Id`?
- Есть `Idempotency-Key` на write?
- Верный `team_role_id`?
- Верный `origin_interface`?
- Есть подписка (`event-subscriptions`) для нужного scope?
- `event-deliveries.summary` без аномального роста `failed_dlq`?
