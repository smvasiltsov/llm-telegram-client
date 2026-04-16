# Interface SDK Kit

Набор документации для разработчика интерфейса (в т.ч. AI-агента), который не знаком с текущей архитектурой.

## Что внутри

- `00_start_here.md` - быстрый старт за 15 минут.
- `01_system_map.md` - как устроена система и где точка интеграции интерфейса.
- `02_http_api_contract.md` - рабочий API-контракт для интерфейсов.
- `03_event_bus_outbox.md` - модель событий, подписки, доставка, retry/DLQ.
- `04_interface_implementation_playbook.md` - пошаговый рецепт реализации нового интерфейса.
- `05_testing_smoke.md` - что прогонять перед merge.
- `06_observability_ops.md` - мониторинг, логи, диагностика.
- `07_troubleshooting.md` - частые проблемы и быстрые проверки.

## Источники истины в коде

- HTTP роуты: `app/interfaces/api/routers/read_only_v1.py`
- API DTO: `app/interfaces/api/schemas/entities.py`
- QA use-case: `app/application/use_cases/qa_api.py`
- Outbox dispatcher: `app/interfaces/api/thread_event_outbox_dispatcher.py`
- БД схема и storage: `app/storage.py`
- Минимальный SDK-контракт интерфейса: `interfaces_sdk/contract.py`
- Шаблон адаптера: `interfaces_sdk/template_adapter.py`

## Кому использовать

- Если интерфейс общается через HTTP API (внешний клиент): начать с `00` -> `02` -> `03`.
- Если интерфейс встраивается внутрь runtime как adapter: начать с `00` -> `01` -> `04`.
