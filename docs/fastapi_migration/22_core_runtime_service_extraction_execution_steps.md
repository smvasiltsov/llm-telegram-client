## Этап 1
- Что делаем: Фиксируем runtime service boundary и контракты взаимодействия API -> Runtime внутри текущего репозитория (команды/события, статусы, error mapping, correlation-id, idempotency ключи).
- DoD: Утверждён минимальный внутренний контракт runtime-execution (request/response/status/error) и список breaking-risk зон для вынесения.

## Этап 2
- Что делаем: Выделяем runtime core orchestration в отдельный модульный слой без Telegram-зависимостей (dispatch, role routing, prompt enrichment, provider call, status transitions).
- DoD: Core runtime запускается через адаптер-интерфейс и не зависит напрямую от Telegram handlers/SDK.

## Этап 3
- Что делаем: Реализуем execution bridge stabilization для HTTP-потока (event enqueue + worker + retry/timeout/lease + terminal persist answer/feed) с единым observability набором.
- DoD: Вопрос из `POST /questions` стабильно проходит `accepted -> queued -> in_progress -> answered/failed/timeout` по контракту.

## Этап 4
- Что делаем: Поднимаем runtime как отдельный сервис-процесс (отдельный entrypoint, конфигурация, health/readiness, single-runner policy, runbook запуска/rollback).
- DoD: Runtime service стартует/останавливается независимо от API, health endpoints и operator controls подтверждены smoke/integration тестами.

## Этап 5
- Что делаем: Переводим Telegram adapter в thin client: приём/отправка сообщений и вызовы runtime API без встроенной доменной оркестрации.
- DoD: Telegram handlers не содержат runtime orchestration логики; обмен с runtime идёт только через согласованный adapter-контракт.

## Этап 6
- Что делаем: Стабилизируем межсервисный контур API <-> Runtime (idempotency, cursor/status consistency, correlation/metrics/logging, error taxonomy) и закрываем интеграционные/e2e гейты.
- DoD: End-to-end цепочка question/answer и orchestration сценарии проходят в CI, гейты зелёные, регрессий Telegram UX нет.

## Этап 7
- Что делаем: Финализируем rollout в production-порядке (поэтапное включение, rollback-план, операционные runbook/sign-off, фиксация residual risks).
- DoD: Подписан финальный sign-off, подтверждён безопасный rollback, этап runtime extraction завершён со статусом GO.
