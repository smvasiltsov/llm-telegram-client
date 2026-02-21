# Orchestrator JSON Schema (fixed)

## Цель
Единый формат входа в LLM для обычных ролей и оркестратора.

Важно: JSON формируется в коде и отправляется в провайдер как текст (string), а не как transport JSON-контракт.

## Общая структура входного payload
```json
{
  "actor": {
    "username": "owner"
  },
  "instruction": {
    "system": "...",
    "message": "...",
    "reply": "..."
  },
  "context": {
    "routing": {
      "trigger_type": "mention_role",
      "mentioned_roles": ["analyst"]
    },
    "reply": {
      "is_reply": false,
      "previous_message": null
    }
  },
  "user_request": {
    "text": "Текст запроса пользователя",
    "recipient": "analyst"
  },
  "llm_answer": {
    "text": null,
    "role_name": null
  },
  "tools": {
    "available": []
  }
}
```

## Значение полей
- `actor.username`: источник сообщения:
  - сообщение от пользователя -> username пользователя;
  - делегация от роли/оркестратора -> имя роли (`orchestrator` для оркестратора);
  - post-response событие в оркестратор -> имя роли, чей ответ отправляется оркестратору.
- `instruction.system`: системный промпт роли.
- `instruction.message`: инструкция к обычному сообщению.
- `instruction.reply`: инструкция для сценария reply.
- `context.routing.trigger_type`: тип триггера маршрутизации (`mention_role | mention_all | orchestrator_all_messages`).
- `context.routing.mentioned_roles`: роли, определенные в текущем маршруте.
- `context.reply.is_reply`: является ли текущий запрос reply на предыдущее сообщение.
- `context.reply.previous_message`: текст сообщения, на которое сделан reply.
- `user_request.text`: исходный текст запроса пользователя.
- `user_request.recipient`: целевой получатель запроса (`имя_роли` или `orchestrator`).
- `llm_answer.text`: ответ роли (заполняется только когда событие отправляется в оркестратор после ответа роли).
- `llm_answer.role_name`: имя роли, которая дала `llm_answer.text`.
- `tools.available`: зарезервировано для будущих tool/mcp сценариев.

## Вариант A: Запрос в обычную роль
```json
{
  "actor": { "username": "owner_username" },
  "instruction": {
    "system": "Ты аналитик",
    "message": "Давай кратко",
    "reply": null
  },
  "context": {
    "routing": {
      "trigger_type": "mention_role",
      "mentioned_roles": ["analyst"]
    },
    "reply": {
      "is_reply": false,
      "previous_message": null
    }
  },
  "user_request": {
    "text": "@analyst дай 3 ключевых риска релиза",
    "recipient": "analyst"
  },
  "llm_answer": {
    "text": null,
    "role_name": null
  },
  "tools": { "available": [] }
}
```

## Вариант B: Делегация role/orchestrator -> role
```json
{
  "actor": { "username": "orchestrator" },
  "instruction": {
    "system": "Ты critic",
    "message": "Проверь гипотезы",
    "reply": null
  },
  "context": {
    "routing": {
      "trigger_type": "mention_role",
      "mentioned_roles": ["critic"]
    },
    "reply": {
      "is_reply": false,
      "previous_message": null
    }
  },
  "user_request": {
    "text": "Проверь риски и добавь контраргументы",
    "recipient": "critic"
  },
  "llm_answer": {
    "text": null,
    "role_name": null
  },
  "tools": { "available": [] }
}
```

## Вариант C: Post-response событие в оркестратор
```json
{
  "actor": { "username": "analyst" },
  "instruction": {
    "system": "Ты оркестратор",
    "message": "Координируй роли",
    "reply": null
  },
  "context": {
    "routing": {
      "trigger_type": "mention_role",
      "mentioned_roles": ["analyst"]
    },
    "reply": {
      "is_reply": false,
      "previous_message": null
    }
  },
  "user_request": {
    "text": "@analyst дай 3 ключевых риска релиза",
    "recipient": "orchestrator"
  },
  "llm_answer": {
    "text": "1) ... 2) ... 3) ...",
    "role_name": "analyst"
  },
  "tools": { "available": [] }
}
```

## Правила обработки
- Для обычных ролей `llm_answer.*` всегда `null`.
- Для post-response вызова оркестратора `llm_answer.*` обязательно заполняется.
- Если ответ оркестратора невалидный JSON, применяется fallback как обычный текст.
- На текущем этапе `context.routing` сохраняется в payload для диагностируемости и обратной совместимости.
