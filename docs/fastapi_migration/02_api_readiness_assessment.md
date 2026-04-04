# 02. Оценка готовности к FastAPI API

## 1. Цель и критерии оценки
- Цель: оценить готовность текущей системы к добавлению FastAPI API поверх существующего функционала (без изменения бизнес-семантики).
- Критерии:
  - выделяемость доменных операций в стабильные use-case/service контракты;
  - предсказуемость state transitions (sessions/pending/queue/busy);
  - управляемость ошибок и валидаций;
  - возможность безопасной конкурентной работы и идемпотентных операций;
  - наблюдаемость и тестируемость на API-уровне.

## 2. Что уже готово

### 2.1 Сильное хранилищное ядро (Storage) с явными сущностями
- Базовые доменные таблицы и методы уже консолидированы в `Storage`.
- Есть team-центричная модель (`teams`, `team_bindings`, `team_roles`) и team-role scoped данные (`provider_user_data_team_role`, skills/prepost по `team_role_id`).
- Источники:
  - `app/storage.py:133`
  - `app/storage.py:146`
  - `app/storage.py:318`
  - `app/storage.py:228`
  - `app/storage.py:3752`
  - `app/storage.py:4115`

### 2.2 Наличие выделенных runtime-сервисов
- Конкурентный runtime вынесен в отдельные сервисы:
  - busy/free + lease/release-delay (`RoleRuntimeStatusService`),
  - FIFO-очередь исполнения (`RoleDispatchQueueService`).
- Источники:
  - `app/services/role_runtime_status.py:52`
  - `app/services/role_runtime_status.py:98`
  - `app/services/role_dispatch_queue.py:31`
  - `app/services/role_dispatch_queue.py:45`

### 2.3 Частичная декомпозиция use-cases
- Для части админ-действий есть слой `app/core/use_cases/*` (операции с team roles / master roles), который уже можно переиспользовать из API.
- Источники:
  - `app/core/use_cases/team_roles.py:1`
  - `app/core/use_cases/master_roles.py:1`

### 2.4 Базовая интерфейсная абстракция
- Есть контракт `CorePort` и runtime loader для интерфейсных адаптеров, что концептуально совместимо с добавлением HTTP-интерфейса.
- Источники:
  - `app/core/contracts/interface_io.py:37`
  - `app/interfaces/runtime/runner.py:14`
  - `app/interfaces/runtime/loader.py:14`

## 3. Ограничения и пробелы

### 3.1 Высокая связность Telegram handlers и доменной логики
- `handlers/*` напрямую работают с runtime/storage/services и формируют пользовательский UX одновременно с доменной операцией.
- Это осложняет переиспользование логики как “чистых” API use-cases.
- Источники:
  - `app/handlers/messages_group.py:40`
  - `app/handlers/messages_group.py:218`
  - `app/handlers/callbacks.py:1`
  - `app/handlers/commands.py:21`

### 3.2 Непоследовательная граница транзакций для составных операций
- Многошаговые операции выполняются несколькими вызовами `Storage` (каждый с собственным `commit`) без единой unit-of-work транзакции.
- В API-сценариях это риск промежуточных состояний при сбоях/ретраях.
- Источники:
  - `app/core/use_cases/team_roles.py:135`
  - `app/core/use_cases/team_roles.py:152`
  - `app/storage.py:1822`
  - `app/storage.py:3279`

### 3.3 Ошибки/валидации ориентированы на Telegram-flow, не на API-контракты
- Преобладает `ValueError` + текстовые ответы в обработчиках; нет единой error taxonomy для HTTP (codes/details/path).
- Источники:
  - `app/storage.py:1998`
  - `app/storage.py:2209`
  - `app/handlers/messages_private.py:263`
  - `app/handlers/commands.py:109`

### 3.4 Авторизация завязана на `owner_user_id` и интерфейсные проверки
- Админ-доступ проверяется в Telegram handlers/callbacks через `owner_user_id`.
- Для FastAPI потребуется вынести policy-слой и унифицированные dependency/guards.
- Источники:
  - `app/handlers/commands.py:30`
  - `app/handlers/callbacks.py:42`
  - `app/interfaces/telegram/adapter.py:76`

### 3.5 Pending/queue часть завязана на process-memory
- `RoleDispatchQueueService` хранит очередь в памяти процесса (без persistence).
- Для API это ограничивает горизонтальное масштабирование и recovery-поведение.
- Источники:
  - `app/services/role_dispatch_queue.py:31`
  - `app/app_factory.py:110`

### 3.6 Наблюдаемость: хорошие логи, но нет стабильной метрик-модели
- В runtime есть информативные логи (`role_queue_wait/dispatch`, pending события), но нет выделенного API-уровня метрик/трейс-корреляции по операциям.
- Источники:
  - `app/services/role_pipeline.py:1321`
  - `app/services/role_pipeline.py:1328`
  - `app/handlers/messages_common.py:76`

### 3.7 Тестовое покрытие сильное для runtime, ограниченное для HTTP-контрактов
- Есть хорошие тесты доменной семантики (inheritance, pending replay, FIFO, reset/remove->add), но нет API contract/serialization/error mapping тестов.
- Источники:
  - `tests/test_ltc13_inheritance_override.py:30`
  - `tests/test_ltc18_pipeline_busy_semantics.py:1049`
  - `tests/test_core_team_roles_use_cases.py:221`

## 4. Вывод по готовности
- Текущая готовность: **частичная (условно 6/10)**.
- Система функционально зрелая на уровне домена и runtime, но перед FastAPI нужны обязательные доработки слоёв:
  - стабилизировать application/use-case boundary,
  - ввести единый error model для API,
  - определить транзакционные границы для составных команд,
  - вынести авторизационную политику из Telegram-слоя,
  - зафиксировать idempotency/consistency контракты для изменяющих операций.

## 5. Трассируемость (код/тесты)
- Domain/storage: `app/storage.py`, `app/models.py`.
- Runtime orchestration: `app/services/role_pipeline.py`, `app/services/role_runtime_status.py`, `app/services/role_dispatch_queue.py`.
- Interface coupling: `app/handlers/*`, `app/interfaces/telegram/adapter.py`.
- Existing use-cases: `app/core/use_cases/*`.
- Behavioral tests: `tests/test_ltc13_inheritance_override.py`, `tests/test_ltc18_pipeline_busy_semantics.py`, `tests/test_core_team_roles_use_cases.py`, `tests/test_root_dir_pending_flow.py`.
