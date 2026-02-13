# Плагины

Плагины — это подключаемые Python‑модули в `plugins/`, которые могут пост‑обрабатывать ответы LLM.

## Структура
```
plugins/
  markdown_answers.py
  markdown_answers.json
```

## Контракт плагина
Файл плагина должен экспортировать функцию `register()` и хук `on_llm_response`.

```python
def register():
    return {
        "id": "markdown_answers",
        "type": "postprocess",
        "version": "1.0",
        "hooks": {
            "on_llm_response": on_llm_response,
        },
    }
```

Хук:
```python
def on_llm_response(payload, ctx, config):
    # payload: {"text": "...", "parse_mode": "markdown|html", "reply_markup": None}
    # ctx: {"chat_id":..., "user_id":..., "role_id":..., "role_name":..., "provider_id":..., "model_id":...}
    # config: dict из plugins/<id>.json
    return payload  # или None, если без изменений
```

## Конфиг плагина
Файл `plugins/<id>.json`:
```json
{
  "enabled": true,
  "web_app_url": "https://example.com/app/",
  "max_inline_chars": 3500,
  "min_chars_for_button": 1200,
  "button_text": "Открыть полностью"
}
```

- `enabled` — включить/выключить плагин.
- `web_app_url` — базовый URL мини‑приложения (обязательно с `/` на конце).
- `max_inline_chars` — максимальная длина текста, которую оставляем в чате.
- `min_chars_for_button` — минимальная длина, начиная с которой включается кнопка.
- `button_text` — подпись кнопки.

## Поведение markdown_answers
- Если текст укладывается в один месседж — плагин не вмешивается.
- Если текст длинный — оставляет первую часть и добавляет кнопку WebApp с полным текстом.
- Граница разреза сдвигается, чтобы не разрывать ```code``` блоки.

## Отключение плагина
Установите `"enabled": false` в его JSON‑конфиге.
