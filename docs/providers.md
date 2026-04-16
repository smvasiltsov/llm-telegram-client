# Провайдеры LLM

Провайдер — это JSON‑конфиг в `llm_providers/*.json`, который описывает:
- базовый URL API;
- контракты запросов (создание сессии, отправка сообщения и т.п.);
- поддерживаемые возможности;
- список моделей;
- user_fields для запроса у пользователя.

## Идентификаторы
- `provider_id` — строка (например `alfagen`, `ollama`, `codex-api`).
- `model_id` — строка (например `llama3.2`, `default`).
- Полный ключ модели: `provider_id:model_id`.

## Возможности (capabilities)
Провайдер может поддерживать:
- `list_sessions`
- `create_session`
- `rename_session`
- `model_select`

Если возможность отключена — бот не пытается вызывать соответствующий эндпоинт.

## User fields
`user_fields` описывает параметры, которые бот должен запросить у пользователя.
Каждое поле имеет:
- `prompt` — текст запроса;
- `scope` — область действия:
  - `provider` — одно значение на провайдера,
  - `role` — значение на каждую роль.

Если поле не задано в конфиге — бот его не запрашивает.

## Поддержка истории
В `history` можно включить отправку последних сообщений:
- `enabled` — включить/выключить,
- `max_messages` — сколько последних сообщений отправлять.

Хранение истории ведётся всегда, отправка зависит от `enabled`.

## Read API: провайдеры и модели
Для получения единого каталога провайдеров и моделей используйте:
- `GET /api/v1/providers/catalog`

Endpoint возвращает:
- список провайдеров (`provider_id`, `name`, `auth_mode`, `capabilities`);
- список моделей каждого провайдера (`model_id`, `label`, `full_id`);
- `default_model` для провайдера (первая модель в отсортированном списке);
- `is_default_provider` для провайдера по `runtime.default_provider_id`.

Пример ответа:
```json
[
  {
    "provider_id": "codex-api",
    "name": "Codex API",
    "auth_mode": "header",
    "capabilities": {
      "send_message": true,
      "create_session": true
    },
    "default_model": "codex-api:gpt-4.1",
    "is_default_provider": true,
    "models": [
      { "model_id": "gpt-4.1", "label": "GPT-4.1", "full_id": "codex-api:gpt-4.1" },
      { "model_id": "gpt-5", "label": "GPT-5", "full_id": "codex-api:gpt-5" }
    ]
  }
]
```

## Пример: Ollama
```json
{
  "id": "ollama",
  "label": "Ollama",
  "base_url": "http://localhost:11434",
  "tls": { "ca_cert_path": null },
  "adapter": "generic",
  "capabilities": {
    "list_sessions": false,
    "create_session": false,
    "rename_session": false,
    "model_select": true
  },
  "auth": { "mode": "none" },
  "user_fields": {},
  "endpoints": {
    "send_message": {
      "path": "/api/chat",
      "method": "POST",
      "request": {
        "body_template": {
          "model": "{{model}}",
          "messages": "{{messages}}",
          "stream": true
        }
      },
      "response": {
        "stream": true,
        "stream_line_prefix": "data:",
        "stream_done_value": "[DONE]",
        "stream_content_path": "message.content"
      }
    }
  },
  "history": { "enabled": false, "max_messages": 20 },
  "models": [
    { "id": "qwen3:1.7b", "label": "qwen3:1.7b" },
    { "id": "mistral:latest", "label": "mistral:latest" }
  ]
}
```
