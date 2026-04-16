# Troubleshooting

## Бот не отвечает в группе
- Проверь, что бот добавлен в группу.
- Проверь, что пишет владелец бота (owner_user_id).
- Проверь логи запуска бота.

## Запрашивается user_field, но не принимает значение
- Убедись, что отвечаешь боту в личке.
- Если значение начинается с `/`, бот должен быть в режиме ожидания поля (иначе команда игнорируется).

## Провайдер не найден
- Убедись, что в `llm_providers/` есть JSON.
- Проверь поле `id`.

## 401 / Unauthorized
- Проверь, требуется ли токен для провайдера.
- Проверь заголовки/куки в контракте.

## CORS ошибка в Obsidian/Postman Web
- Симптом: `No 'Access-Control-Allow-Origin' header` при запросах из `app://obsidian.md`.
- Причина: браузерный клиент делает `OPTIONS` preflight, а API не разрешает origin.
- Решение:
  - Для read-only API (`api_service`): задай `API_CORS_ALLOWED_ORIGINS`.
  - Для runtime service (`runtime_service`): задай `RUNTIME_CORS_ALLOWED_ORIGINS`.
- Формат: список origin через запятую.

Пример:

```bash
export API_CORS_ALLOWED_ORIGINS="app://obsidian.md,http://localhost:3000,http://127.0.0.1:3000"
export RUNTIME_CORS_ALLOWED_ORIGINS="app://obsidian.md,http://localhost:3000,http://127.0.0.1:3000"
```

После изменения перезапусти сервисы.
