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
