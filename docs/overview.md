# Обзор проекта

Этот документ даёт краткое понимание архитектуры и ключевых сущностей.

## Структура приложения
- `bot.py` — entrypoint: загрузка конфигурации, инициализация runtime, lifecycle Telegram application.
- `app/app_factory.py` — сборка runtime и регистрация Telegram handlers.
- `app/runtime.py` — единый контейнер зависимостей (`RuntimeContext`), который хранится в `bot_data["runtime"]`.
- `app/handlers/` — слой Telegram-обработчиков:
- `app/handlers/commands.py` — `/groups`, `/roles`, `/tools`, `/bash`, reset/set prompt.
- `app/handlers/callbacks.py` — inline UI callbacks (`/groups` навигация и действия по ролям).
- `app/handlers/membership.py` — события добавления/удаления бота, учет групп.
- `app/handlers/messages_private.py` — private flow (pending token/user_fields, password flow bash, приватные шаги UI).
- `app/handlers/messages_group.py` — групповой flow (буферизация, маршрутизация по ролям, ответы в группу).
- `app/handlers/messages_common.py` — общие helper-функции для private/group handlers.
- `app/services/` — бизнес-утилиты, не привязанные к конкретному handler:
- `app/services/formatting.py` — рендер и безопасная отправка форматированного ответа.
- `app/services/prompt_builder.py` — выбор модели/провайдера и сборка финального prompt.
- `app/services/plugin_pipeline.py` — сборка Telegram reply_markup для plugin postprocess.
- `app/services/tool_exec.py` — выполнение tool-команд (bash), логирование и рендер результата.
- `app/tools/` — реестр/адаптер/реализации инструментов.
- `app/storage.py` + `app/models.py` — работа с SQLite и доменными сущностями.

## Основной поток
1) Бот добавляется в группу.
2) Сообщения пользователя маршрутизируются на роль.
3) У роли выбрана LLM‑модель (фактически это провайдер + модель).
4) Бот создает/использует сессию провайдера и отправляет сообщение.
5) Ответ возвращается в группу.

## Основные сущности
- **Group** — телеграм‑группа.
- **Role** — роль бота (настройки подсказок, модели, инструкции).
- **GroupRole** — связка роли и группы (override промпта, модель и т.п.).
- **Provider** — описание API LLM в `llm_providers/*.json`.
- **Session** — сессия LLM, привязанная к роли и группе.
- **User fields** — значения, которые бот запрашивает у пользователя (например token, working_dir).

## Где хранится состояние
Хранилище — SQLite (файл в `config.json`):
- роли, группы, настройки ролей;
- сессии;
- история сообщений;
- user_fields (значения, введённые пользователем).

## Форматирование ответов
В `config.json` есть параметры:
- `formatting.mode` — `html` или `markdown` (по умолчанию `markdown`).
- `formatting.allow_raw_html` — разрешает отправку «сырого» HTML от LLM (актуально для режима `html`).

Если включён raw‑режим, бот сначала пытается отправить текст как HTML, а при ошибке Telegram API автоматически делает fallback на экранированный текст.
