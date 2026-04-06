# 21. Runtime Service Extraction High-Level Plan

Дата: **2026-04-06**
Статус: **Draft**

## 1. Цель
- Зафиксировать high-level план выноса runtime в отдельный сервис.
- Закрыть текущий gap Stage 5, когда `POST /api/v1/questions` может оставаться в `accepted`.
- Сохранить обратную совместимость Telegram UX и текущих API-контрактов.

## 2. Контекст и проблема
- Текущее поведение Stage 5:
  - `POST /api/v1/questions` создаёт запись Q/A и возвращает `202`;
  - часть запросов может оставаться в `accepted`, если execution-мост API->runtime не завершён.
- Следствие:
  - пользователь видит статус, но не видит движения к `queued/in_progress/answered`;
  - операционно сложнее диагностировать end-to-end путь.
- Целевой вектор:
  - сначала закрыть gap execution внутри текущего решения (M1),
  - затем выделить runtime orchestration в отдельный сервис (M2),
  - после этого упростить Telegram до thin client (M3).

## 3. Scope и ограничения
- In scope:
  - high-level этапный план миграции runtime в отдельный сервис;
  - execution bridge для статусов Q/A;
  - декомпозиция контрактов: public API / internal runtime API;
  - целевые quality gates и rollout-подход.
- Out of scope:
  - немедленная реализация всех этапов;
  - новые пользовательские фичи Telegram/Web;
  - изменение продуктовой UX-логики Telegram.
- Ограничения:
  - owner-only authz;
  - additive-only API эволюция;
  - без изменений Telegram UX;
  - без новых user-facing функций в этой миграции.

## 4. Этап 1 (M1): Execution Bridge для `accepted -> queued/in_progress/...`
### 4.1 Цель этапа
- Обеспечить deterministic продвижение Q/A статусов после `POST /api/v1/questions`.
- Подключить runtime execution к созданным вопросам без изменения внешнего UX Telegram.

### 4.2 High-level изменения
- Ввести execution bridge между API-слоем вопросов и runtime orchestration:
  - перевод `accepted -> queued`;
  - запуск исполнения;
  - фиксация переходов `queued -> in_progress -> answered|failed|timeout|cancelled`.
- Явно обработать idempotency/retry семантику для bridge-операций.
- Добавить correlation-id сквозь bridge и status transitions.

### 4.3 Целевые артефакты
- Спецификация execution bridge (поток, статусы, error mapping).
- Обновлённые application/use-case контракты переходов.
- Минимальный ops-runbook по диагностике stuck-статусов.

### 4.4 Целевые CI-гейты (recommended)
- `stage5_execution_bridge_gates`:
  - unit/use-case тесты статусов и переходов;
  - integration контракт `POST /questions` + async/status progression;
  - idempotency/retry coverage;
  - regression Telegram UX.

### 4.5 DoD этапа (GO/NO-GO)
- `accepted` не остаётся конечным рабочим состоянием для валидных запросов.
- Переходы статусов подтверждены тестами и наблюдаемы в логах/метриках.
- Ошибочные ветки детерминированно маппятся в status/error contract.
- Merge-gate этапа стабильно зелёный.

## 5. Этап 2 (M2): Выделение Core Runtime в отдельный сервис
### 5.1 Цель этапа
- Отделить runtime orchestration от Telegram/HTTP адаптеров в самостоятельный service boundary.

### 5.2 Границы сервиса
- В runtime-service:
  - orchestration и dispatch;
  - role pipeline (pre/post, skills, provider calls);
  - status transitions и runtime queue policy.
- Вне runtime-service:
  - public HTTP API adapter (FastAPI);
  - Telegram adapter (на первом этапе по-прежнему внутри монорепо, но без бизнес-оркестрации).

### 5.3 High-level изменения
- Вынести core runtime API в отдельный внутренний контракт (sync/async операции исполнения).
- Подготовить инфраструктурный режим отдельного процесса runtime.
- Развести зависимости и lifecycle (API-процесс vs runtime-процесс).

### 5.4 Целевые артефакты
- Runtime service API spec (internal).
- Схема взаимодействия API <-> runtime (commands/events/status channel).
- Операционный runbook отдельного runtime процесса.

### 5.5 Целевые CI-гейты (recommended)
- `runtime_service_extraction_gates`:
  - integration API<->runtime;
  - fault-injection (runtime unavailable/retry);
  - contract tests internal runtime API;
  - observability sanity (metrics/log/correlation).

### 5.6 DoD этапа (GO/NO-GO)
- Runtime orchestration исполняется в отдельном service boundary.
- Public API сохраняет контракт (additive-only).
- Нет UX-регрессий Telegram при переключении на новый runtime path.
- Описан и проверен rollback до предыдущего режима.

## 6. Этап 3 (M3): Telegram как Thin Client
### 6.1 Цель этапа
- Упростить Telegram до transport/UI-адаптера без orchestration-логики.

### 6.2 High-level изменения
- Перевести Telegram path на вызов runtime/public API контрактов.
- Убрать дублирующую orchestration-логику из Telegram handlers.
- Сохранить текущие тексты/кнопки/поведение (strict backward compatibility).

### 6.3 Целевые артефакты
- Telegram adapter contract (что вызывает, что отображает).
- Документ миграции Telegram path -> thin client.
- Обновлённый runbook инцидентов на стыке Telegram/runtime.

### 6.4 Целевые CI-гейты (recommended)
- `telegram_thin_client_regression_gates`:
  - snapshot/contract tests Telegram UX;
  - end-to-end сценарии ключевых интентов;
  - совместимость callback/command flows.

### 6.5 DoD этапа (GO/NO-GO)
- Telegram не содержит core runtime orchestration.
- Все критичные Telegram сценарии проходят regression без UX-изменений.
- Межсервисная диагностика (trace/log/metrics) достаточна для эксплуатации.

## 7. Контракты API/Runtime (кратко)
### 7.1 Public API (FastAPI)
- Внешний контракт остаётся в `/api/v1`.
- Для Q/A:
  - create/status/get/resolve/journal/thread/feed;
  - additive-only изменения;
  - owner-only authz в рамках текущего security baseline.

### 7.2 Internal Runtime API
- Команды исполнения:
  - enqueue/dispatch question;
  - управление жизненным циклом выполнения роли;
  - публикация terminal result/error.
- Ответы runtime:
  - подтверждение принятия команды;
  - runtime execution outcome с machine codes.

### 7.3 Событийная/очередная модель и status semantics
- Каноничные статусы Q/A: `accepted -> queued -> in_progress -> answered|failed|cancelled|timeout`.
- Runtime является источником истины по execution-state.
- Public API отображает runtime-state в стабильный внешний status/error contract.

## 8. Milestones и порядок релиза
- M1:
  - execution bridge закрывает gap `accepted`;
  - status progression становится обязательным контрактом.
- M2:
  - runtime выделен в отдельный сервисный контур;
  - API и runtime работают как раздельные процессы.
- M3:
  - Telegram переведён на thin client-модель;
  - orchestration остаётся только в runtime-service.
- Критический путь зависимостей:
  - M1 обязателен до M2 (иначе переносит незакрытый статусный gap).
  - M2 обязателен до M3 (иначе thin client некуда направлять).

## 9. Риски и mitigation
- Технические риски:
  - рассинхронизация статусов между API и runtime;
  - ошибки idempotency/retry на границе сервисов;
  - несовместимость внутренних контрактов при эволюции.
- Операционные риски:
  - недостаточная наблюдаемость межсервисных сбоев;
  - рост латентности/таймаутов при разделении процессов.
- Риски совместимости:
  - регрессии Telegram сценариев при переключении path.
- План снижения рисков:
  - phased rollout с feature flags;
  - обязательные regression gates для Telegram/API;
  - rollback-ready деплой и runbook до каждого cutover.

## 10. Rollout strategy
- Фазирование rollout.
  - Phase A: bridge в текущем контуре (M1);
  - Phase B: dual-run/partial traffic на runtime-service (M2);
  - Phase C: Telegram thin client cutover (M3).
- Backward compatibility checks.
  - owner-only/additive-only invariant;
  - Telegram UX parity checks;
  - OpenAPI/contract snapshot gates.
- Rollback подход.
  - быстрый откат на предыдущий path через config flags;
  - сохранение совместимых контрактов между версиями.

## 11. Рекомендуемые quality gates (сводно)
- Перечень целевых gating jobs.
  - `stage5_execution_bridge_gates`
  - `runtime_service_extraction_gates`
  - `telegram_thin_client_regression_gates`
- Минимальные критерии прохождения между этапами.
  - переход к следующему milestone только при GO текущего;
  - зелёные contract/integration/regression suites;
  - подтверждённый rollback drill.

## 12. Next Steps
- Список ближайших действий после утверждения плана.
  - Утвердить high-level план и приоритет M1.
  - Создать execution checklist для M1 с конкретными задачами.
  - Зафиксировать draft internal runtime API контракта (M2 prep).
