# 04. План внедрения и риски

## 1. Цель документа
- Зафиксировать реалистичный поэтапный план внедрения FastAPI API поверх текущей системы без изменения действующей runtime-семантики (pending/FIFO/busy/replay).
- Определить гейты качества и риски, которые должны быть закрыты до перехода к следующему этапу.

## 2. Принципы внедрения
- FastAPI добавляется как новый interface adapter, без отключения Telegram-пути.
- Поведенческий baseline рантайма обязателен перед каждым write-этапом API.
- Составные доменные операции переводятся в application-layer use-cases до публикации write endpoint-ов.
- Любые изменения, влияющие на queue/pending, сопровождаются целевыми регрессионными тестами.

## 3. Пошаговый roadmap

### Этап 1. Application boundary stabilization (без HTTP)
- Цель:
  - отделить доменные операции от Telegram-specific кода и стабилизировать use-case слой.
- Работы:
  - вынести операции из `handlers/*` в application services/use-cases;
  - унифицировать доменные ошибки и формат бизнес-результатов;
  - определить транзакционные границы для multi-step операций.
- Артефакты:
  - application services для teams/team_roles/sessions/skills/prepost/runtime;
  - единый error mapping на уровне application слоя;
  - документированные transaction boundaries.
- Гейт перехода:
  - базовые операции вызываются без `Update/ContextTypes`;
  - ключевые runtime-тесты зелёные.

### Этап 2. FastAPI foundation (read-only)
- Цель:
  - поднять FastAPI-каркас с безопасным read-only API.
- Работы:
  - реализовать структуру `routers/services/schemas/dependencies`;
  - добавить owner-only authz dependency;
  - открыть read endpoint-ы по core сущностям (teams, team_roles, runtime status, sessions).
- Артефакты:
  - FastAPI app factory и набор read routers;
  - OpenAPI схема;
  - API contract tests для read маршрутов.
- Гейт перехода:
  - read API стабилен, backward compatibility с Telegram подтверждена.

### Этап 3. Write API для админ-операций
- Цель:
  - добавить изменяющие API-операции без изменения существующей runtime семантики.
- Работы:
  - PATCH/PUT/POST операции для team-role overrides, skills/prepost, reset session, role bindings;
  - зафиксировать idempotency и conflict behavior;
  - ввести консистентный HTTP error contract.
- Артефакты:
  - write routers + DTO schemas;
  - documented idempotency rules;
  - расширенные integration/contract tests.
- Гейт перехода:
  - write API работает на целевых сценариях;
  - baseline тесты рантайма и командных use-cases зелёные.

### Этап 4. Runtime/API hardening
- Цель:
  - довести API и runtime до эксплуатационной устойчивости.
- Работы:
  - добавить correlation/trace и операционные метрики;
  - формализовать ограничения in-memory queue (single-instance policy);
  - подготовить runbook (операции, инциденты, rollback).
- Артефакты:
  - метрики и унифицированные runtime/API логи;
  - эксплуатационный регламент;
  - smoke/integration сценарии для прод-готовности.
- Гейт завершения:
  - наблюдаемость и инцидентный контур готовы;
  - риски высокого приоритета закрыты или приняты с mitigation.

## 4. Risk matrix

### R1. Регрессия pending/FIFO/busy
- Вероятность: высокая.
- Impact: высокий.
- Подтверждение в коде:
  - `app/services/role_pipeline.py`
  - `app/services/role_runtime_status.py`
  - `app/services/role_dispatch_queue.py`
- Mitigation:
  - baseline регрессий обязателен перед и после каждого write-релиза API;
  - изоляция runtime-изменений от transport-кода.

### R2. Частичная запись в multi-step операциях
- Вероятность: средняя/высокая.
- Impact: высокий.
- Подтверждение в коде:
  - `app/core/use_cases/team_roles.py`
  - `app/storage.py`
- Mitigation:
  - application-level unit-of-work и явные rollback policy;
  - idempotency ключи для критичных write-команд.

### R3. Несовместимость авторизации Telegram/API
- Вероятность: средняя.
- Impact: высокий.
- Подтверждение в коде:
  - `app/handlers/commands.py`
  - `app/handlers/callbacks.py`
  - `app/interfaces/telegram/adapter.py`
- Mitigation:
  - вынести policy layer и использовать единый authz dependency в API.

### R4. Ограничение масштабирования из-за in-memory queue
- Вероятность: средняя.
- Impact: средний/высокий.
- Подтверждение в коде:
  - `app/services/role_dispatch_queue.py`
  - `app/app_factory.py`
- Mitigation:
  - зафиксировать single-runtime constraint в первой версии API;
  - подготовить план выноса queue-state во внешний backend как отдельный этап.

### R5. Нестабильные API контракты ошибок
- Вероятность: средняя.
- Impact: средний.
- Подтверждение в коде:
  - `app/storage.py`
  - `app/handlers/messages_private.py`
  - `app/handlers/commands.py`
- Mitigation:
  - единая taxonomy ошибок и централизованный exception mapper для FastAPI.

## 5. Контрольные проверки на этапах
- Перед Этапом 2:
  - доменные операции доступны через application services без Telegram-context.
- Перед Этапом 3:
  - read API стабилен, authz dependency валиден, OpenAPI согласован.
- Перед Этапом 4:
  - write API покрыт contract/integration тестами;
  - критичные runtime regression tests зелёные.
- Перед release:
  - runbook готов;
  - приняты/закрыты высокие риски;
  - подтверждена обратная совместимость Telegram-путей.

## 6. Трассируемость (код и тесты)
- Домен/хранилище:
  - `app/storage.py`
  - `app/models.py`
- Runtime orchestration:
  - `app/services/role_pipeline.py`
  - `app/services/role_runtime_status.py`
  - `app/services/role_dispatch_queue.py`
- Use-cases:
  - `app/core/use_cases/team_roles.py`
  - `app/core/use_cases/master_roles.py`
- Интерфейсный слой:
  - `app/handlers/*`
  - `app/interfaces/telegram/adapter.py`
- Базовый regression набор:
  - `tests/test_ltc13_inheritance_override.py`
  - `tests/test_ltc18_pipeline_busy_semantics.py`
  - `tests/test_core_team_roles_use_cases.py`
  - `tests/test_root_dir_pending_flow.py`
