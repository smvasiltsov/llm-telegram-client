# Шаблон конфига LLM‑провайдера

Этот документ описывает единый формат конфигов в папке `llm_providers/`.

## Минимальный шаблон
```json
{
  "id": "provider-id",
  "label": "Provider Label",
  "base_url": "https://api.example.com",
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
      "path": "/send",
      "method": "POST",
      "request": {
        "body_template": { "prompt": "{{content}}" }
      },
      "response": { "content_path": "answer" }
    }
  },
  "history": { "enabled": false, "max_messages": 20 },
  "models": [{ "id": "default", "label": "Default" }]
}
```

## Описание полей
### id
Уникальный идентификатор провайдера.

### label
Человекочитаемое имя для UI.

### base_url
Базовый URL API.

### tls.ca_cert_path
Путь к CA‑сертификату. Если не нужен — `null`.

### adapter
Всегда `generic`.

### capabilities
Указывает, какие операции поддерживает API:
- `list_sessions`
- `create_session`
- `rename_session`
- `model_select`

### auth.mode
Сейчас используется только для справки:
- `none` — токен не нужен.

### user_fields
Поля, которые бот запрашивает у пользователя.
Пример:
```json
"user_fields": {
  "working_dir": {
    "prompt": "Введите рабочую директорию...",
    "scope": "role"
  }
}
```

### endpoints
Контракты API.

#### list_sessions
```json
{
  "path": "/sessions",
  "method": "GET",
  "response": {
    "list_path": "sessions",
    "item_id_path": "session_id"
  }
}
```

#### create_session
```json
{
  "path": "/sessions",
  "method": "POST",
  "request": {
    "body_template": { "working_dir": "[[[working_dir]]]" }
  },
  "response": { "session_id_path": "session_id" }
}
```

#### send_message
```json
{
  "path": "/sessions/{session_id}/send-prompt",
  "method": "POST",
  "request": {
    "body_template": { "prompt": "{{content}}" }
  },
  "response": { "content_path": "answer" }
}
```

#### rename_session
```json
{
  "path": "/rename-session",
  "method": "PUT",
  "request": {
    "body_template": {
      "name": "{{name}}",
      "sessionId": "{{session_id}}"
    }
  }
}
```

## Плейсхолдеры
В шаблонах поддерживаются:
- `{{session_id}}`
- `{{content}}`
- `{{model}}`
- `{{messages}}`
- `{{name}}`
- `[[[user_field]]]` — значение из user_fields.

## Streaming‑ответы
Для SSE/stream:
```json
"response": {
  "stream": true,
  "stream_line_prefix": "data:",
  "stream_done_value": "[DONE]",
  "stream_content_path": "choice.content"
}
```

