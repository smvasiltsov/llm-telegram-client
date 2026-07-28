# LLM Telegram Client

`llm-telegram-client-in-dev` это role-based LLM runtime для запуска AI-ролей, orchestration-сценариев и управляемых tool/skill workflow.

Исторически проект вырос из Telegram-бота, но сейчас это не просто transport-слой для чата, а runtime-платформа, которая:

- маршрутизирует запросы по `team + role + provider/model`;
- хранит конфигурацию, сессии и runtime-состояние в SQLite;
- даёт моделям вызывать локальные skills и tools;
- поддерживает pre/post-processing pipeline;
- поднимает HTTP API для read/write/QA/runtime сценариев;
- умеет запускать интерфейсы через runtime contract.

Важно: в коде и API сохранены legacy naming и Telegram-oriented термины для обратной совместимости. Это осознанное решение: текущий API уже используется не только Telegram-путём, и резкое переименование сломало бы существующие интеграции.

## Для чего нужен проект

Проект нужен как единый backend для role-based AI-ассистентов и связанных runtime-сценариев:

- запуск AI-ролей для команд, чатов и интерфейсов;
- управление master-role каталогом и team-specific overrides;
- изолированное хранение сессий по пользователю, команде и роли;
- выполнение многошаговых skill/tool flow;
- orchestration, Q/A и thread-based runtime сценарии;
- единый API для управления и наблюдения за состоянием системы.

## Возможности

- Обработка Telegram group/private flow с вызовом ролей по упоминанию.
- Поддержка owner-scoped административного UX для ролей, групп и инструментов.
- Несколько LLM providers и models из `llm_providers/*.json`.
- Team/team-role модель с override-конфигурацией на уровне конкретной команды.
- Structured skill calling loop с ограничением шагов и защитой от повторов.
- Guarded tool execution, включая ограниченный bash.
- Pre/post-processing обработчики вокруг prompt/response pipeline.
- FastAPI API под `/api/v1` для catalog/read/write/QA/recovery сценариев.
- Отдельный runtime service API для health, readiness и dispatch/worker состояния.
- Интерфейсный runtime contract для подключения transport-модулей.

## Ключевые понятия

- `Team`
  Доменная команда. Обычно связана с Telegram group через binding, но сама по себе не равна transport-сущности.
- `Master role`
  Базовая конфигурация роли из `roles_catalog/*.json`.
- `Team role`
  Привязка master-role к конкретной команде с override-параметрами.
- `Session`
  Изолированный контекст по связке пользователь + команда + роль.
- `Skill`
  Capability, которую модель может вызвать в структурированном виде.
- `Tool`
  Runtime-инструмент, например guarded bash.
- `Provider`
  Внешний LLM backend с набором моделей и auth/runtime правилами.
- `Interface`
  Transport- или integration-модуль, через который runtime взаимодействует с внешним миром.

## Как устроена система

На высоком уровне система состоит из пяти блоков:

1. Runtime core
   Хранит зависимости, policy, orchestration state и execution services.
2. Storage layer
   SQLite хранит team bindings, team roles, sessions, provider fields, thread events, answers и observability-данные.
3. Interface layer
   Отвечает за transport-адаптеры и lifecycle интерфейсов.
4. API layer
   Даёт HTTP-доступ к catalog/read/write/QA/runtime сценариям.
5. Execution extensions
   Skills, tools, plugins и pre/post-processing.

Упрощённый runtime flow:

```text
Входящее сообщение / API-запрос
-> resolve team + role
-> resolve session + provider/model
-> pre-processing
-> LLM / skill loop / tools
-> post-processing
-> answer / thread event / API response
```

## Архитектура по директориям

- `app/`
  Основной код приложения: runtime assembly, application/use-case layer, handlers, API transport, authz, contracts и services.
- `skills/`
  Built-in skills: файловые операции, Jira, Confluence, Confluence auto-sync, OpenAPI indexer, plan supervisor.
- `prepost_processing/`
  Built-in pre/post-processing processors.
- `plugins/`
  Плагины форматирования и пост-обработки текстового вывода.
- `llm_providers/`
  JSON-конфиги провайдеров и моделей.
- `roles_catalog/`
  Master-role JSON catalog.
- `interfaces_sdk/`
  Публичный контракт для внешних interface modules.
- `tests/`
  Контрактные, регрессионные, smoke и e2e-style тесты.
- `scripts/`
  Вспомогательные runner'ы, smoke checks и stage gates.
- `deploy/systemd/`
  Примеры unit-файлов для раздельного запуска сервисов.

## Режимы запуска

### 1. Основной interface runtime

```bash
python3 bot.py
```

Главный entrypoint. Загружает `config.json` и `.env`, собирает `RuntimeContext` и запускает активный интерфейс через `InterfaceRuntimeRunner`.

### 2. Явный Telegram service

```bash
python3 telegram_service.py
```

Принудительно запускает именно Telegram interface и использует его transport-specific конфигурацию.

### 3. Основной API service

```bash
python3 api_service.py
```

Поднимает FastAPI приложение на `127.0.0.1:8080` с endpoint'ами `/api/v1`.

### 4. Runtime service

```bash
python3 runtime_service.py
```

Поднимает отдельный runtime service API. По умолчанию использует `127.0.0.1:8091`.

## Быстрый старт

### 1. Установка зависимостей

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 2. Создание конфигурации

```bash
cp config.example.json config.json
```

Если нужен новый Fernet key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Заполнение `config.json`

Заполните обязательные значения:

- `database_path`
- `encryption_key`
- `owner_user_id`
- `telegram_bot_token`, если используется Telegram interface

### 4. Дополнительные секреты в `.env`

`.env` опционален, но используется для значений, которые неудобно хранить прямо в `config.json`, например:

- `BASH_DANGEROUS_PASSWORD`
- provider-specific секреты и токены

### 5. Запуск

Для основного runtime path:

```bash
python3 bot.py
```

Для backend-only сценария без Telegram polling:

```bash
python3 api_service.py
python3 runtime_service.py
```

## Конфигурация

Ключевые секции `config.json`:

- `telegram_bot_token`
  Токен Telegram-бота. Для backend-only запуска может быть пустым.
- `database_path`
  Путь до SQLite базы.
- `encryption_key`
  Ключ для шифрования чувствительных токенов.
- `owner_user_id`
  Идентификатор владельца, которому разрешены административные действия.
- `routing.require_bot_mention`
  Нужно ли явное упоминание бота в group flow.
- `llm.timeout_sec`
  Таймаут LLM-запросов.
- `formatting.mode`
  Формат ответа: `markdown` или `html`.
- `plugin_server.*`
  Настройки внутреннего plugin text server.
- `runtime_status.*`
  Параметры задержек и runtime transitions.
- `skills.*`
  Prompt и лимиты для skill loop.
- `tools.*`
  Включение tools и guarded bash.
- `interface.*`
  Активный интерфейс, modules dir, runtime mode и transport-specific параметры.
- `dispatch.*`
  Параметры dispatch/runner режима.
- `thread_events.delivery.*`
  Явное включение доставки thread events во внешние интерфейсы.
- `migration.team.*`
  Rollout-флаги для team migration.

Полный пример структуры лежит в [`config.example.json`](config.example.json).

## Роли и команды

### Master roles

Master-role каталог хранится в [`roles_catalog/`](roles_catalog/). Это основной source of truth для:

- системного prompt;
- extra instruction;
- default model;
- общих характеристик роли.

Identity роли определяется по имени JSON-файла, а не по полю внутри файла.

### Team roles

`Team role` связывает master-role с конкретной командой и может переопределять:

- system prompt;
- extra instruction;
- model override;
- active/inactive state;
- mention/public name;
- orchestrator mode;
- working dir и root dir;
- skills;
- pre/post-processing processors.

### Где хранится состояние

SQLite хранит:

- team bindings;
- team role bindings и overrides;
- user role sessions;
- conversation history;
- provider user fields;
- thread events и answers;
- observability-логи (`skill_runs`, `tool_runs`).

## Skills, Tools и Processing

### Skills

Skills автоматически discover'ятся из `skills/*/skill.yaml`.

В репозитории есть built-in skills, включая:

- файловые операции;
- Jira;
- Confluence;
- Confluence auto-sync;
- OpenAPI indexer;
- plan supervisor.

Модель может вызвать skill через structured JSON-ответ. Runtime выполнит skill и продолжит loop до финального ответа или срабатывания guard-лимитов.

### Tools

Tools существуют отдельно от skills. В текущей сборке может регистрироваться `bash` tool.

Защиты для bash:

- явное включение через config;
- allowlist безопасных команд;
- ограничение по working directories;
- ограничение по timeout и размеру вывода;
- trusted path для privileged command execution.

### Pre/post-processing

Pre/post processors discover'ятся из `prepost_processing/*/processor.yaml`.

Это детерминированные обработчики вокруг основного LLM flow: они могут подготовить payload перед запросом и преобразовать ответ после него.

## HTTP API

Основной API публикуется через `api_service.py` и доступен под `/api/v1`.

По смыслу он покрывает несколько зон:

- catalog/read API;
- write/admin API;
- QA/orchestration API;
- runtime status / dispatch health / recovery сценарии.

Важно: в названиях модулей и части DTO до сих пор есть legacy naming вроде `read_only` и Telegram-oriented полей. Это не означает, что API read-only или жёстко привязан только к Telegram. Эти имена оставлены ради совместимости.

## Legacy и обратная совместимость

Проект развивается эволюционно. Поэтому в коде и API есть legacy naming:

- `telegram_*` поля и методы;
- имена модулей вроде `read_only_*`;
- команды и UX алиасы, сохранившиеся со старых этапов.

Это сделано намеренно:

- текущий API уже используется внешними интерфейсами;
- резкое переименование полей и DTO сломало бы совместимость;
- внутренняя архитектура постепенно становится более transport-neutral, но внешний контракт сохраняется стабильным.

Если вы подключаете новый интерфейс, ориентируйтесь на текущий API и существующие contract points, а не на буквальную интерпретацию legacy naming.

## Структура репозитория

Короткая карта корня:

- [`app/`](app/) — основной runtime и transport/API слои
- [`skills/`](skills/) — skills
- [`prepost_processing/`](prepost_processing/) — pre/post-processing
- [`plugins/`](plugins/) — output plugins
- [`llm_providers/`](llm_providers/) — конфиги провайдеров
- [`roles_catalog/`](roles_catalog/) — master-role каталог
- [`tests/`](tests/) — тесты
- [`scripts/`](scripts/) — smoke/stage utilities
- [`docs/`](docs/) — дополнительная документация

## Тестирование и валидация

Базовый запуск тестов:

```bash
python3 -m unittest
```

Полезные runner'ы и smoke checks:

```bash
python3 -m scripts.skills_runner list
python3 -m scripts.prepost_processing_runner --prepost-processing-id echo
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
bash scripts/stage5_thin_client_gates.sh
```

Покрытие включает Telegram flows, API contracts, storage migrations, runtime transitions, dispatch bridge, thread events, skills и interface runtime.

## Ограничения и текущий статус

- По умолчанию используется SQLite.
- В коде и API есть legacy naming, связанный с Telegram и историческими этапами развития.
- Поддерживается `interface.runtime_mode=single`.
- Проект хорошо подходит для локальной разработки и controlled deployment, но production hardening требует отдельной operational настройки.

## Дополнительная документация

- [`docs/overview.md`](docs/overview.md) — краткий обзор проекта и актуальных сущностей
- [`docs/dev.md`](docs/dev.md) — заметки по разработке и валидации
- [`docs/fastapi_migration/README.md`](docs/fastapi_migration/README.md) — документы по API/runtime migration
- [`interfaces_sdk/README.md`](interfaces_sdk/README.md) — контракт для interface modules
- [`interfaces_sdk/kit/README.md`](interfaces_sdk/kit/README.md) — onboarding и implementation kit для интерфейсов
- [`app/interfaces/telegram/README.md`](app/interfaces/telegram/README.md) — Telegram interface module
- [`full_reset/README.md`](full_reset/README.md) — утилита полного сброса состояния
