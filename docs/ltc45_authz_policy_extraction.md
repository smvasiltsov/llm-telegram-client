# LTC-45: Вынос authz/policy из Telegram owner-check

## Цель
Убрать размазанные проверки `owner_user_id` из Telegram-слоя и перевести их на единый переиспользуемый policy/authz-слой, FastAPI-ready.

## Реализованный слой
- Пакет: `app/application/authz/*`
- Контракты:
  - `AuthzAction`, `AuthzRole`
  - `AuthzActor`, `AuthzResourceContext`
  - `AuthzDecision`
  - `AuthzService.authorize(...) -> Result[AuthzDecision]`
- Базовая policy:
  - `OwnerOnlyAuthzService` (owner-only, расширяемо до RBAC)
  - deny: `AppError(code=auth.unauthorized, http_status=403)`

## Матрица действий (текущий scope)
1. `telegram.commands.admin`
   - Policy: owner-only
   - Required role: `owner`
   - Интеграция: `app/handlers/commands.py` (`_is_owner_authorized`)
2. `telegram.callbacks.admin`
   - Policy: owner-only
   - Required role: `owner`
   - Интеграция: `app/handlers/callbacks.py` (`_is_owner_callback`)
3. `telegram.bootstrap.admin`
   - Policy: owner-only
   - Required role: `owner`
   - Интеграция: `app/interfaces/telegram/adapter.py` (`resolve_bootstrap_owner_user_id`)

## Telegram adapter helpers
- `app/application/authz/telegram_adapter.py`
  - `actor_from_update`, `actor_from_callback`
  - `resource_ctx_from_update`, `resource_ctx_from_callback`
  - `action_for_private_owner_command`, `action_for_callback_admin`, `action_for_bootstrap_admin`

## Runtime wiring
- `RuntimeContext` расширен полем `authz_service`.
- В `build_runtime` подключается `OwnerOnlyAuthzService(owner_user_id=config.owner_user_id)`.

## Совместимость UX
- Сохранено 1:1:
  - команды: deny по-прежнему молча игнорируется;
  - callbacks: deny по-прежнему делает `query.answer()` и завершает обработку;
  - тексты, callback_data, порядок ответов не изменены.
- Добавлен fallback для legacy runtime в тестовых фикстурах без `authz_service` (возврат к `owner_user_id` проверке).

## Тесты
- `tests/test_ltc45_authz_policy.py`:
  - allow/deny для owner-only policy;
  - контракт deny (`auth.unauthorized`, `403`);
  - Telegram DTO adapter helpers.
- Регрессии:
  - `tests/test_ltc42_callback_use_cases.py`
  - `tests/test_ltc43_error_contracts.py`
  - `tests/test_ltc42_group_runtime_use_cases.py`
  - `tests/test_ltc42_private_pending_use_cases.py`

## Расширение для FastAPI (следующий этап)
1. Добавить policy map для ролей `admin/member` поверх текущих `AuthzAction`.
2. Переиспользовать `AuthzService` в dependency FastAPI (`authorize(action, actor, resource_ctx)`).
3. Централизовать аудит deny-событий в одном application-level hook.
