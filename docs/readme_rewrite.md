# README Audit And Rewrite

Этот документ подготовлен по фактическому состоянию кода в репозитории и предназначен как замена устаревшему `README.md`.

## 1. Audit текущего README

Ниже перечислены все смысловые пункты текущего `README.md` и их статус по коду.

### Overview

- `llm-telegram-client-in-dev is a role-based LLM runtime with Telegram as the primary interface`:
  актуально. Это подтверждается точками входа `bot.py`, `telegram_service.py`, Telegram-адаптером и runtime-сборкой.
- `Telegram transport for group and private flows`:
  актуально. Есть отдельные group/private handlers и Telegram interface adapter.
- `configurable LLM providers from JSON contracts in llm_providers/`:
  актуально. Провайдеры грузятся из `llm_providers/*.json`.
- `team and role configuration stored in SQLite`:
  актуально, но формулировку лучше уточнить. SQLite хранит runtime-состояние, team bindings, team roles, sessions, history и служебные сущности. Master-role source of truth сейчас лежит в `roles_catalog/*.json`, а не только в БД.
- `skill execution and tool calling`:
  актуально.
- `pre/post-processing pipelines`:
  актуально.
- `HTTP API for runtime, read, and orchestration scenarios`:
  в целом актуально. Но полезно разделять:
  `api_service.py` поднимает основной FastAPI `/api/v1`,
  `runtime_service.py` поднимает отдельный runtime-service API для worker/health/dispatch health.

### Core Concepts

- `owner_user_id`: актуально. Сейчас базовая authz-политика по коду owner-only.
- `Team`, `Role`, `Session`, `Skill`, `Pre/post-processing`:
  актуально.
- Нужна поправка терминологии:
  team обычно связан с Telegram group через binding, а не равен группе буквально.

### What The Project Can Do

- `Handle Telegram group requests addressed to a role mention such as @analyst`:
  актуально.
- `Manage private pending flows when a provider requires extra user fields or credentials`:
  актуально.
- `Route requests across multiple provider/model definitions from llm_providers/*.json`:
  актуально.
- `Run role pipelines with busy-state protection and dispatch queue semantics`:
  актуально.
- `Let LLM roles call local skills in a guarded execution loop`:
  актуально.
- `Expose runtime/read/orchestration data through FastAPI endpoints under /api/v1`:
  актуально.
- `Load interface modules through the interface runtime contract in interfaces_sdk/`:
  актуально.
- `Support role catalogs, plan supervision, thread events, and runtime status tracking`:
  актуально.

### Repository Layout

- Описание директорий в целом актуально.
- Нужна поправка:
  `app/` уже содержит не только Telegram/runtime assembly, но и application layer, contracts, authz, API schemas, interface runtime и bridge worker-логику.

### Requirements

- `Python 3.9+`:
  неактуально. Код использует синтаксис `X | Y`, значит нужен минимум Python 3.10+.
- `Telegram bot token from BotFather`:
  актуально для Telegram интерфейса.
- `Access to at least one configured LLM backend`:
  актуально. Без провайдеров runtime не соберётся.

### Installation

- Команды установки актуальны.
- Но в README стоит явно указать, что нужен `config.json`, и что некоторые сценарии также зависят от `.env`.

### Configuration

- Раздел в целом актуален.
- Нужна важная поправка:
  `.env` используется не только для providers/tools вообще, но и для `BASH_DANGEROUS_PASSWORD`, если включён guarded bash.
- Список ключевых config sections актуален.

### Entry Points

- `python bot.py`:
  актуально. Это главный entrypoint интерфейсного runtime.
- `python telegram_service.py`:
  актуально, но формулировку лучше уточнить. Этот entrypoint принудительно запускает именно Telegram interface и передаёт параметры thin-client режима.
- `python api_service.py`:
  актуально.
- `python runtime_service.py`:
  актуально.

### Typical Telegram Flow

- Все шаги актуальны.
- Стоит уточнить, что обработка групповых сообщений проходит через буферизацию и routing-plan перед flush в runtime.

### Role Configuration

- Формулировка в целом актуальна.
- Нужна поправка:
  роли экспортируются из legacy DB только на first run, но текущий source of truth master-role каталога уже `roles_catalog/*.json`.

### Skills And Tools

- Описание structured skill calling актуально.
- Список встроенных skills актуален по директории `skills/`.
- Ограничения bash в README описаны верно, но полезно уточнить:
  safe command не требует password confirmation, всё остальное требует trusted execution path.

### API Surface

- Описание в целом актуально.
- Нужна поправка:
  router и некоторые builder'ы до сих пор называются `read_only`, хотя фактически внутри уже есть read/write/QA/recovery endpoint'ы.

### Development And Validation

- `python -m unittest`:
  актуально.
- Указанные smoke/stage scripts существуют и актуальны.
- Стоит явно добавить, что тестовое покрытие большое и включает contract/smoke/regression, но запуск полного набора может быть долгим.

### Notes

- Все три замечания в разделе `Notes` по сути актуальны.
- При этом текущий README недостаточно явно фиксирует переходное состояние:
  много `legacy` и `read_only` naming ещё не убрано из кода.

## 2. Новый README

# LLM Telegram Client

`llm-telegram-client-in-dev` это role-based LLM runtime с Telegram как основным transport-слоем и FastAPI как управляющим/API-слоем.

Проект уже давно вышел за рамки "бота с одним промптом". Сейчас это runtime-платформа, которая:

- принимает сообщения из Telegram group/private flows;
- маршрутизирует запрос по team + role + provider/model;
- хранит сессии, runtime status, bindings и execution metadata в SQLite;
- даёт моделям вызывать локальные skills и tools;
- поддерживает pre/post-processing pipeline;
- поднимает HTTP API для чтения состояния, мутаций, Q/A orchestration и service health;
- умеет запускать интерфейсы через interface runtime contract.

## Что умеет проект

- Обрабатывать сообщения в Telegram-группах с обращением к роли, например `@analyst`.
- Поддерживать owner-scoped Telegram UX для администрирования групп, ролей и инструментов.
- Работать с несколькими LLM providers и models, описанными в `llm_providers/*.json`.
- Хранить team bindings, team roles, sessions, answer/thread-event данные и runtime metadata в SQLite.
- Выполнять structured skill-calling loop с ограничением числа шагов и защитой от повторов.
- Выполнять guarded tool calls, включая ограниченный bash.
- Применять pre/post-processing обработчики вокруг prompt/response pipeline.
- Публиковать FastAPI endpoints под `/api/v1` для catalog/read/write/QA/recovery сценариев.
- Поднимать отдельный runtime service API для health и dispatch/worker состояния.
- Загружать интерфейсные модули по контракту из `interfaces_sdk/`.

## Основные сущности

- `owner_user_id`
  Идентификатор владельца, которому разрешён административный доступ. Текущая authz-политика по умолчанию owner-only.
- `Team`
  Доменная команда. В Telegram обычно связана с группой через team binding.
- `Master role`
  Базовая конфигурация роли из `roles_catalog/*.json`.
- `Team role`
  Привязка master-role к конкретной team с override-параметрами.
- `Session`
  Изолированный контекст по связке user + team + role.
- `Skill`
  Модельно-вызываемая capability с manifest/contract.
- `Tool`
  Runtime-инструмент, например guarded bash.
- `Pre/post-processing`
  Детерминированные обработчики до и после LLM-вызова.

## Актуальная архитектура

- `bot.py`
  Основной entrypoint. Загружает `config.json`, `.env`, собирает `RuntimeContext`, запускает активный интерфейс через `InterfaceRuntimeRunner`.
- `telegram_service.py`
  Явный Telegram-only entrypoint. Полезен, когда нужно принудительно стартовать именно Telegram interface и thin-client параметры.
- `api_service.py`
  Основной FastAPI сервис на `127.0.0.1:8080` с роутами `/api/v1`.
- `runtime_service.py`
  Отдельный runtime-service API для health/readiness/dispatch health и фонового bridge worker.
- `app/app_factory.py`
  Сборка runtime: storage, providers, skills, tools, plugin server, auth/authz, dispatch services.
- `app/interfaces/telegram/`
  Telegram transport module.
- `app/interfaces/api/`
  FastAPI boundary, DTO, routers, error mapping, bridge worker и outbox dispatcher.
- `app/interfaces/runtime/`
  Loader/runner интерфейсных модулей.

## Структура репозитория

- `app/`
  Основной код приложения: runtime assembly, application/use-case layer, Telegram handlers, API transport, authz, contracts и services.
- `skills/`
  Built-in skills: filesystem helpers, Jira, Confluence, Confluence auto-sync, OpenAPI indexer, plan supervisor.
- `prepost_processing/`
  Built-in pre/post processing processors.
- `plugins/`
  Форматирующие и output-related плагины.
- `llm_providers/`
  JSON-конфиги LLM providers и их моделей.
- `roles_catalog/`
  Master-role JSON catalog.
- `interfaces_sdk/`
  Публичный контракт для внешних интерфейсных модулей.
- `tests/`
  Контрактные, регрессионные, smoke и e2e-style тесты.
- `scripts/`
  Вспомогательные runner'ы, smoke checks и stage gates.
- `deploy/systemd/`
  Примеры unit-файлов для раздельного запуска сервисов.

## Требования

- Python 3.10+
- Telegram bot token, если используется Telegram interface
- Хотя бы один корректно описанный provider в `llm_providers/*.json`
- `config.json`, собранный из `config.example.json`

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

Если нужен новый Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

После этого заполните все `REPLACE_ME` значения в `config.json`.

## Конфигурация

Основные поля `config.json`:

- `telegram_bot_token`
  Токен Telegram-бота.
- `database_path`
  Путь до SQLite базы.
- `encryption_key`
  Ключ для шифрования чувствительных токенов.
- `owner_user_id`
  Telegram user id владельца.
- `routing.require_bot_mention`
  Требовать ли явное упоминание бота в group flow.
- `llm.timeout_sec`
  Таймаут LLM-запросов.
- `formatting.mode`
  Формат ответа: `markdown` или `html`.
- `plugin_server.*`
  Настройки внутреннего plugin text server.
- `runtime_status.*`
  Тайминги runtime transition и skill-to-LLM delay.
- `skills.*`
  Prompt для skill loop, лимит шагов, follow-up mode.
- `tools.*`
  Включение tools и guarded bash.
- `interface.*`
  Активный интерфейс, modules dir, runtime mode, Telegram thin-client параметры.
- `dispatch.*`
  Политика dispatch/runner режима.
- `migration.team.*`
  Флаги rollout для team migration.

`.env` опционален, но реально используется минимум для секретов и служебных значений вроде `BASH_DANGEROUS_PASSWORD`.

## Точки запуска

### 1. Основной interface runtime

```bash
python bot.py
```

Использует `interface.active` из `config.json` и запускает соответствующий interface adapter.

### 2. Явный Telegram service

```bash
python telegram_service.py
```

Фиксированно запускает Telegram interface, даже если вы хотите развести Telegram transport и API topology более явно.

### 3. Основной API service

```bash
python api_service.py
```

Поднимает FastAPI приложение на `127.0.0.1:8080`.

### 4. Runtime service

```bash
python runtime_service.py
```

Поднимает отдельный FastAPI сервис для runtime worker/health сценариев. По умолчанию использует `127.0.0.1:8091`.

## Telegram UX

В Telegram transport сейчас зарегистрированы owner-oriented команды:

- `/groups`
- `/roles`
- `/tools`
- `/bash` при включённом bash tool
- `/group_roles`
- `/role_set_prompt`
- `/role_reset_session`

Также есть callback-based UI для выбора групп, ролей и управляющих операций.

### Типичный group flow

1. Бот добавляется в Telegram group.
2. Пользователь отправляет сообщение с упоминанием роли, например `@analyst`.
3. Если включён `routing.require_bot_mention`, в сообщении нужно упомянуть и бота.
4. Сообщение проходит prepare/routing этап и буферизацию.
5. Runtime определяет team, team role, session, provider/model, skills и processing pipeline.
6. Если провайдер требует дополнительные user fields, часть flow может продолжиться в private chat.
7. Ответ возвращается обратно в transport.

## Роли и каталог

- Master-role source of truth сейчас находится в `roles_catalog/*.json`.
- При первом запуске поддерживается export из legacy DB path в `roles_catalog/`.
- Team-specific overrides хранятся в SQLite.
- Для team role можно переопределять:
  - system prompt;
  - extra instruction;
  - model override;
  - active/inactive state;
  - mention/public name;
  - orchestrator behavior;
  - working dir и root dir;
  - набор skills;
  - набор pre/post-processing processors.

## Skills, tools и processing pipeline

### Skills

Skills автоматически discover'ятся из `skills/*/skill.yaml`.

Встроенные skills:

- `fs_read_file`
- `fs_list_dir`
- `fs_write_file`
- `fs_save_blind_spot_artifacts`
- `jira`
- `confluence`
- `confluence_auto_sync`
- `mcp_openapi_indexer`
- `plan_supervisor`

Модель может вызвать skill через structured JSON-ответ. Runtime выполняет skill и продолжает loop до финального ответа или до срабатывания guard-лимитов.

### Tools

Tools управляются отдельно от skill loop. В текущей сборке runtime может регистрироваться `bash` tool.

Защиты для bash:

- явное включение через config;
- allowlist безопасных команд;
- ограничение по working directories;
- ограничение по timeout и размеру вывода;
- password-confirmed path для privileged command execution.

### Pre/post-processing

Pre/post processors discover'ятся из `prepost_processing/*/processor.yaml`.

В репозитории есть готовые примеры и встроенные процессоры, включая `echo`, `exec-processing` и `crud-processing`.

## API

Основной API находится в `api_service.py` и публикуется под `/api/v1`.

По коду там есть endpoint-группы для:

- teams и team roles;
- master role catalog и catalog errors;
- providers;
- skills и pre/post-processing registries;
- runtime status и dispatch health;
- sessions;
- Q/A questions, answers, threads и orchestrator feed;
- recovery/reset операций;
- write-path мутаций для teams, roles, skills, pre/post bindings, working/root dir и session reset.

Важно:
часть внутренних модулей всё ещё называется `read_only`, но это уже историческое имя. Текущий router не является только read-only.

## Runtime service API

`runtime_service.py` поднимает отдельный сервис с endpoint'ами уровня runtime/process:

- `GET /health/live`
- `GET /health/ready`
- `GET /runtime/dispatch-health`

На старте сервис также может поднимать bridge worker и thread-event outbox dispatcher.

## Разработка и проверка

Базовый запуск тестов:

```bash
python -m unittest
```

Полезные runner'ы и smoke checks:

```bash
python3 -m scripts.skills_runner list
python3 -m scripts.prepost_processing_runner --prepost-processing-id echo
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
bash scripts/stage5_thin_client_gates.sh
```

В репозитории большое тестовое покрытие: Telegram flows, API contracts, storage migrations, runtime transitions, dispatch bridge, thread events, skills и interface runtime.

## Ограничения и текущее состояние

- Проект находится в переходном состоянии между legacy naming и новой runtime/API архитектурой.
- В коде ещё много `legacy` и `read_only` имён, хотя функциональность уже шире.
- SQLite подходит для локальной разработки и небольших инсталляций, но для production topology потребуется более жёсткая operational story.
- Базовая authz-политика owner-only. Для multi-user admin/API сценариев этого мало.
- `bot.py` и `telegram_service.py` частично пересекаются по назначению; различие в явном Telegram-only запуске и thin-client config.

## Дополнительная документация

- `docs/overview.md`
- `docs/fastapi_migration/README.md`
- `interfaces_sdk/README.md`
- `interfaces_sdk/kit/README.md`
- `app/interfaces/telegram/README.md`
- `docs/dev.md`
