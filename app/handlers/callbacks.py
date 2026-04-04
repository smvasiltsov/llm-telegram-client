from __future__ import annotations

import logging
from uuid import uuid4

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.application.dependencies import (
    resolve_pending_replay_dependencies,
    resolve_runtime_orchestration_dependencies,
    resolve_storage_uow_dependencies,
)
from app.application.authz import (
    action_for_callback_admin,
    actor_from_callback,
    resource_ctx_from_callback,
)
from app.application.contracts import log_structured_error, to_telegram_message
from app.application.use_cases.callback_role_actions import RoleActionRequest, execute_role_action
from app.core.use_cases import (
    bind_master_role_to_group,
    clear_team_role_prompt,
    clear_team_role_reply_prefix,
    clear_team_role_suffix,
    delete_team_role_binding,
    get_team_role_state,
    list_team_role_states,
    list_telegram_groups,
    master_roles_list_text,
    reset_team_role_session,
    resolve_team_id,
    resolve_team_role_id,
    set_team_role_model,
)
from app.llm_providers import model_label
from app.role_catalog_service import (
    create_master_role_json,
    ensure_role_identity_by_name,
    list_active_master_role_names,
    refresh_role_catalog,
    update_master_role_json,
)
from app.runtime import RuntimeContext
from app.services.prompt_builder import resolve_provider_model
from app.storage import Storage
from app.utils import split_message

logger = logging.getLogger("bot")


def _bot_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    application = getattr(context, "application", None)
    data = getattr(application, "bot_data", None)
    if isinstance(data, dict):
        return data
    return {}


def _resolve_storage(context: ContextTypes.DEFAULT_TYPE, runtime: RuntimeContext) -> Storage:
    storage_result = resolve_storage_uow_dependencies(_bot_data(context))
    if storage_result.is_ok and storage_result.value is not None:
        return storage_result.value.storage
    return runtime.storage


def _resolve_pending_maps(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: RuntimeContext,
) -> tuple[dict[int, tuple[int, int]], dict[int, dict[str, object]]]:
    pending_result = resolve_pending_replay_dependencies(_bot_data(context))
    if pending_result.is_ok and pending_result.value is not None:
        return pending_result.value.pending_prompts, pending_result.value.pending_role_ops
    pending_prompts = getattr(runtime, "pending_prompts", {})
    pending_role_ops = getattr(runtime, "pending_role_ops", {})
    if not isinstance(pending_prompts, dict):
        pending_prompts = {}
    if not isinstance(pending_role_ops, dict):
        pending_role_ops = {}
    return pending_prompts, pending_role_ops


def _resolve_provider_data(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: RuntimeContext,
) -> tuple[list[object], dict[str, object], dict[str, object]]:
    runtime_result = resolve_runtime_orchestration_dependencies(_bot_data(context))
    if runtime_result.is_ok and runtime_result.value is not None:
        return (
            runtime_result.value.provider_models,
            runtime_result.value.provider_model_map,
            runtime_result.value.provider_registry,
        )
    provider_models = getattr(runtime, "provider_models", [])
    provider_model_map = getattr(runtime, "provider_model_map", {})
    provider_registry = getattr(runtime, "provider_registry", {})
    if not isinstance(provider_models, list):
        provider_models = []
    if not isinstance(provider_model_map, dict):
        provider_model_map = {}
    if not isinstance(provider_registry, dict):
        provider_registry = {}
    return provider_models, provider_model_map, provider_registry


async def _is_owner_callback(query: CallbackQuery, runtime: RuntimeContext) -> bool:
    actor = actor_from_callback(query)
    if actor is None:
        await query.answer()
        return False
    authz_service = getattr(runtime, "authz_service", None)
    if authz_service is None:
        if int(actor.user_id) != int(getattr(runtime, "owner_user_id", -1)):
            await query.answer()
            return False
        return True
    result = authz_service.authorize(
        action=action_for_callback_admin(),
        actor=actor,
        resource_ctx=resource_ctx_from_callback(query),
    )
    if result.is_error:
        await query.answer()
        return False
    if not (result.value and result.value.allowed):
        await query.answer()
        return False
    return True


def _log_master_role_updated(
    *,
    user_id: int,
    role_name: str,
    changed_fields: list[str],
    operation: str,
    source: str,
) -> None:
    logger.info(
        "master_role_updated user_id=%s role=%s changed_fields=%s operation=%s source=%s",
        user_id,
        role_name,
        ",".join(changed_fields),
        operation,
        source,
    )


def _team_id(storage: Storage, group_id: int) -> int:
    return resolve_team_id(storage, group_id)


def _team_role_id(storage: Storage, group_id: int, role_id: int, *, ensure_exists: bool = False) -> int:
    if ensure_exists:
        with storage.transaction(immediate=True):
            team_role_id = resolve_team_role_id(storage, group_id, role_id, ensure_exists=True)
    else:
        team_role_id = resolve_team_role_id(storage, group_id, role_id, ensure_exists=False)
    if team_role_id is None:
        raise ValueError(f"Team role not found: group_id={group_id} role_id={role_id}")
    return int(team_role_id)


def _list_telegram_groups(storage: Storage):
    return list_telegram_groups(storage)


def _preview_text(value: str | None, *, max_len: int = 140) -> str:
    text = (value or "").strip()
    if not text:
        return "(пусто)"
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _runtime_status_caption(storage: Storage, team_role_id: int | None) -> tuple[str, str | None]:
    if team_role_id is None:
        return "FREE", None
    status = storage.get_team_role_runtime_status(team_role_id)
    if status is None:
        return "FREE", None
    state = "BUSY" if status.status == "busy" else "FREE"
    return state, status.preview_text


def _master_roles_keyboard(storage: Storage, runtime: RuntimeContext) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(text="➕ Создать master-role", callback_data="mrole_create")])
    for role_name in list_active_master_role_names(runtime):
        role_id: int | None = None
        try:
            role_id = ensure_role_identity_by_name(runtime=runtime, storage=storage, role_name=role_name).role_id
        except Exception:
            role_id = None
        bindings = storage.list_team_role_bindings_for_role(role_id, active_only=True) if role_id is not None else []
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"@{role_name} ({len(bindings)})",
                    callback_data=f"mrole_name:{role_name}",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def _master_roles_list_text(runtime: RuntimeContext, *, max_issues: int = 10) -> str:
    return master_roles_list_text(runtime, max_issues=max_issues)


def _master_role_card_text(storage: Storage, runtime: RuntimeContext, role_name: str) -> str:
    catalog_role = runtime.role_catalog.get(role_name)
    if catalog_role is None:
        raise ValueError(f"Master-role not found in catalog: {role_name}")
    role_id: int | None = None
    try:
        role_id = ensure_role_identity_by_name(runtime=runtime, storage=storage, role_name=role_name).role_id
    except Exception:
        role_id = None
    bindings = storage.list_team_role_bindings_for_role(role_id, active_only=True) if role_id is not None else []
    lines = [
        f"Master-role: @{catalog_role.role_name}",
        f"role_name: `{catalog_role.role_name}`",
        f"Модель по умолчанию: {catalog_role.llm_model or '(не задана)'}",
        "",
        f"System prompt: {_preview_text(catalog_role.base_system_prompt)}",
        f"Instruction: {_preview_text(catalog_role.extra_instruction)}",
        "",
        "Привязки к командам:",
    ]
    if not bindings:
        lines.append("- (нет привязок)")
    else:
        for b in bindings:
            team_id = int(b["team_id"])
            team_name = str(b["team_name"] or f"team:{team_id}")
            tg_id = b.get("telegram_group_id")
            tg_title = b.get("telegram_group_title")
            display = str(b.get("display_name") or catalog_role.role_name)
            status = "ON" if bool(b.get("enabled")) else "OFF"
            mode = str(b.get("mode") or "normal")
            if tg_id is not None:
                title = str(tg_title or team_name)
                lines.append(f"- {title} ({tg_id}) -> @{display} [{status}|{mode}]")
            else:
                lines.append(f"- {team_name} (team_id={team_id}) -> @{display} [{status}|{mode}]")
    return "\n".join(lines)


async def _handle_master_roles_navigation(
    query: CallbackQuery,
    data: str,
    storage: Storage,
    runtime: RuntimeContext,
) -> bool:
    if data == "mroles:list":
        await query.edit_message_text(
            _master_roles_list_text(runtime),
            reply_markup=_master_roles_keyboard(storage, runtime),
        )
        await query.answer()
        return True
    if data == "mrole_create":
        runtime.pending_role_ops[query.from_user.id] = {
            "mode": "master_create",
            "step": "name",
        }
        await query.edit_message_text(
            "Отправь внутреннее имя master-role (латиница, цифры, underscore).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data="mroles:list")]]
            ),
        )
        await query.answer()
        return True
    if data.startswith("mrole_name:"):
        role_name = data.split(":", 1)[1]
        try:
            card_text = _master_role_card_text(storage, runtime, role_name)
        except ValueError:
            await query.edit_message_text(
                "Master-role не найдена в каталоге.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data="mroles:list")]]
                ),
            )
            await query.answer()
            return True
        await query.edit_message_text(
            card_text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text="➕ Добавить в команду", callback_data=f"mrole_add_name:{role_name}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="mroles:list")],
                ]
            ),
        )
        await query.answer()
        return True
    if data.startswith("mrole_add_name:"):
        role_name = data.split(":", 1)[1]
        groups = _list_telegram_groups(storage)
        if not groups:
            await query.edit_message_text(
                "Нет доступных команд Telegram для привязки.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mrole_name:{role_name}")]]
                ),
            )
            await query.answer()
            return True
        keyboard = [
            [
                InlineKeyboardButton(
                    text=(group.title or str(group.group_id)),
                    callback_data=f"mrole_bind_name:{role_name}:{group.group_id}",
                )
            ]
            for group in groups
        ]
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"mrole_name:{role_name}")])
        await query.edit_message_text(
            "Выбери команду для привязки роли:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("mrole_bind_name:"):
        _, role_name, group_id_str = data.split(":", 2)
        group_id = int(group_id_str)
        bound_role_name, created = bind_master_role_to_group(runtime, storage, group_id=group_id, role_name=role_name)
        note = "привязана к" if created else "уже привязана к"
        await query.edit_message_text(
            f"Роль @{bound_role_name} {note} команде {group_id}.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ К роли", callback_data=f"mrole_name:{role_name}")]]
            ),
        )
        await query.answer()
        return True
    return False


async def _handle_master_role_create_model(
    query: CallbackQuery,
    data: str,
    storage: Storage,
    runtime: RuntimeContext,
) -> bool:
    if not data.startswith("mrole_create_model:"):
        return False
    model_name = data.split(":", 1)[1]
    pending_roles = runtime.pending_role_ops
    state = pending_roles.get(query.from_user.id)
    if not state or state.get("mode") != "master_create" or state.get("step") != "model_select":
        await query.answer()
        return True

    provider_model_map = runtime.provider_model_map
    if model_name != "__skip__" and model_name not in provider_model_map:
        await query.edit_message_text(
            "Модель не найдена в llm_providers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data="mroles:list")]]
            ),
        )
        await query.answer()
        return True
    model = None if model_name == "__skip__" else model_name
    role_name = str(state["role_name"])
    prompt = str(state.get("prompt", ""))
    instruction = str(state.get("instruction", ""))
    create_master_role_json(
        runtime=runtime,
        storage=storage,
        role_name=role_name,
        base_system_prompt=prompt,
        extra_instruction=instruction,
        llm_model=model,
    )
    pending_roles.pop(query.from_user.id, None)
    await query.edit_message_text(
        f"Master-role @{role_name} создана.",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(text="➕ Добавить в команду", callback_data=f"mrole_add_name:{role_name}")],
                [InlineKeyboardButton(text="Открыть карточку", callback_data=f"mrole_name:{role_name}")],
            ]
        ),
    )
    await query.answer()
    return True


def _role_public_name(storage: Storage, group_id: int, role_id: int) -> str:
    return get_team_role_state(storage, group_id, role_id).public_name


def _group_role_caption(storage: Storage, group_id: int, role_id: int) -> str:
    group_role = get_team_role_state(storage, group_id, role_id)
    status = "on" if group_role.enabled else "off"
    mode = "orch" if group_role.mode == "orchestrator" else "normal"
    return f"@{_role_public_name(storage, group_id, role_id)} [{status}|{mode}]"


def _group_roles_keyboard(storage: Storage, group_id: int) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for group_role in list_team_role_states(storage, group_id):
        status = "ON" if group_role.enabled else "OFF"
        mode = "ORCH" if group_role.mode == "orchestrator" else "ROLE"
        team_role_id = _team_role_id(storage, group_id, group_role.role_id, ensure_exists=False)
        run_state, _ = _runtime_status_caption(storage, team_role_id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"@{group_role.public_name} [{status}|{mode}|{run_state}]",
                    callback_data=f"role:{group_id}:{group_role.role_id}",
                )
            ]
        )
    return rows


def _role_actions_keyboard(group_id: int, role_id: int, *, enabled: bool, mode: str) -> InlineKeyboardMarkup:
    toggle_enabled_text = "⏸ Отключить роль" if enabled else "▶️ Включить роль"
    toggle_mode_text = "🎯 Снять оркестратор" if mode == "orchestrator" else "🎯 Сделать оркестратором"
    toggle_mode_cb = (
        f"act:set_mode_normal:{group_id}:{role_id}"
        if mode == "orchestrator"
        else f"act:set_mode_orchestrator:{group_id}:{role_id}"
    )
    keyboard = [
        [InlineKeyboardButton(text=toggle_enabled_text, callback_data=f"act:toggle_enabled:{group_id}:{role_id}")],
        [InlineKeyboardButton(text=toggle_mode_text, callback_data=toggle_mode_cb)],
        [InlineKeyboardButton(text="🛠 Skills", callback_data=f"act:skills:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="🧩 Pre/Post Processing", callback_data=f"act:prepost_processing:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Системный промпт", callback_data=f"act:set_prompt:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Инструкция к сообщениям", callback_data=f"act:set_suffix:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Инструкция для реплаев", callback_data=f"act:set_reply_prefix:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="LLM-модель", callback_data=f"act:set_model:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Master defaults", callback_data=f"act:master_defaults:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="🔒 Lock Groups", callback_data=f"act:lock_groups:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Переименовать роль", callback_data=f"act:rename_role:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Сбросить сессию", callback_data=f"act:reset_session:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="Удалить роль", callback_data=f"act:delete_role:{group_id}:{role_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _master_defaults_keyboard(group_id: int, role_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text="✏️ Системный промпт", callback_data=f"act:master_set_prompt:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="🧹 Очистить промпт", callback_data=f"act:master_clear_prompt:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="✏️ Инструкция к сообщениям", callback_data=f"act:master_set_suffix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="🧹 Очистить инструкцию", callback_data=f"act:master_clear_suffix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="🤖 LLM-модель", callback_data=f"act:master_set_model:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="🧹 Сбросить модель", callback_data=f"act:master_clear_model:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
        ]
    )


def _master_defaults_text(runtime: RuntimeContext, role_id: int) -> str:
    role = runtime.storage.get_role_by_id(role_id)
    if role is None:
        return "Master-role не найдена."
    model_value = role.llm_model
    if not model_value:
        model_label_text = "(не задана)"
    elif model_value in runtime.provider_model_map:
        model_obj = runtime.provider_model_map.get(model_value)
        provider = runtime.provider_registry.get(model_obj.provider_id) if model_obj else None
        model_label_text = model_label(model_obj, provider) if model_obj else model_value
    else:
        model_label_text = f"{model_value} (недоступна)"
    lines = [
        f"Master defaults для @{role.role_name}",
        "",
        f"Системный промпт: {_preview_text(role.base_system_prompt, max_len=180)}",
        f"Инструкция к сообщениям: {_preview_text(role.extra_instruction, max_len=180)}",
        f"LLM-модель по умолчанию: {model_label_text}",
    ]
    return "\n".join(lines)


def _role_skills_keyboard(runtime: RuntimeContext, storage: Storage, group_id: int, role_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    current = {item.skill_id: item for item in storage.list_role_skills_for_team_role(team_role_id)}
    for spec in sorted(runtime.skills_registry.list_specs(), key=lambda x: x.skill_id):
        enabled = bool(current.get(spec.skill_id).enabled) if spec.skill_id in current else False
        mark = "ON" if enabled else "OFF"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"[{mark}] {spec.name} ({spec.skill_id}, {spec.mode})",
                    callback_data=f"sktoggle:{group_id}:{role_id}:{spec.skill_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")])
    return InlineKeyboardMarkup(rows)


def _role_prepost_processing_keyboard(runtime: RuntimeContext, storage: Storage, group_id: int, role_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    current = {item.prepost_processing_id: item for item in storage.list_role_prepost_processing_for_team_role(team_role_id)}
    for spec in sorted(runtime.prepost_processing_registry.list_specs(), key=lambda x: x.prepost_processing_id):
        enabled = bool(current.get(spec.prepost_processing_id).enabled) if spec.prepost_processing_id in current else False
        mark = "ON" if enabled else "OFF"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"[{mark}] {spec.name} ({spec.prepost_processing_id})",
                    callback_data=f"pptoggle:{group_id}:{role_id}:{spec.prepost_processing_id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")])
    return InlineKeyboardMarkup(rows)


async def _handle_groups_navigation(query: CallbackQuery, data: str, storage: Storage) -> bool:
    if data.startswith("grp:"):
        group_id = int(data.split(":", 1)[1])
        keyboard = _group_roles_keyboard(storage, group_id)
        keyboard.append([InlineKeyboardButton(text="➕ Добавить роль", callback_data=f"addrole:{group_id}")])
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back:groups")])
        await query.edit_message_text(
            f"Роли группы {group_id}:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data == "back:groups":
        groups = _list_telegram_groups(storage)
        keyboard = [
            [InlineKeyboardButton(text=(group.title or "(без названия)"), callback_data=f"grp:{group.group_id}")]
            for group in groups
        ]
        await query.edit_message_text(
            "Выбери группу:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("role:"):
        _, group_id_str, role_id_str = data.split(":", 2)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        group_role = get_team_role_state(storage, group_id, role_id)
        state = f"enabled={'yes' if group_role.enabled else 'no'}, mode={group_role.mode}"
        team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=False)
        run_state, preview = _runtime_status_caption(storage, team_role_id)
        preview_line = f"\npreview: {_preview_text(preview, max_len=100)}" if preview else ""
        await query.edit_message_text(
            f"Роль @{_role_public_name(storage, group_id, role_id)} ({state}, runtime={run_state}).{preview_line}\nВыбери действие:",
            reply_markup=_role_actions_keyboard(
                group_id,
                role_id,
                enabled=group_role.enabled,
                mode=group_role.mode,
            ),
        )
        await query.answer()
        return True
    return False


def _lock_groups_keyboard(storage: Storage, group_id: int, role_id: int) -> InlineKeyboardMarkup:
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    current = {item.lock_group_id: item for item in storage.list_lock_groups_for_team_role(team_role_id, active_only=True)}
    all_groups = storage.list_role_lock_groups(active_only=True)
    rows: list[list[InlineKeyboardButton]] = []

    for group in current.values():
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➖ {group.name}",
                    callback_data=f"lockg:remove:{group_id}:{role_id}:{group.lock_group_id}",
                )
            ]
        )
    for group in all_groups:
        if group.lock_group_id in current:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"➕ {group.name}",
                    callback_data=f"lockg:add:{group_id}:{role_id}:{group.lock_group_id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🆕 Создать группу и добавить",
                callback_data=f"lockg:create:{group_id}:{role_id}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")])
    return InlineKeyboardMarkup(rows)


def _lock_groups_text(storage: Storage, group_id: int, role_id: int) -> str:
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    run_state, preview = _runtime_status_caption(storage, team_role_id)
    linked = storage.list_lock_groups_for_team_role(team_role_id, active_only=True)
    lines = [
        f"Lock groups для @{_role_public_name(storage, group_id, role_id)}",
        f"Runtime: {run_state}",
    ]
    if preview:
        lines.append(f"Preview: {_preview_text(preview, max_len=100)}")
    lines.append("")
    lines.append("Текущие группы:")
    if not linked:
        lines.append("- (нет)")
    else:
        for item in linked:
            lines.append(f"- {item.name}")
    lines.append("")
    lines.append("Нажми ➕/➖ для управления зависимостями.")
    return "\n".join(lines)


async def _handle_lock_groups(query: CallbackQuery, data: str, storage: Storage) -> bool:
    if data.startswith("lockg:create:"):
        _, _, group_id_str, role_id_str = data.split(":", 3)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
        lock_group_name = f"lock_group_{team_role_id}_{uuid4().hex[:6]}"
        lock_group = storage.create_role_lock_group(lock_group_name, description="LTC-18 auto-created")
        storage.add_team_role_to_lock_group(lock_group.lock_group_id, team_role_id)
        await query.edit_message_text(
            _lock_groups_text(storage, group_id, role_id),
            reply_markup=_lock_groups_keyboard(storage, group_id, role_id),
        )
        await query.answer("Группа создана и привязана")
        return True
    if data.startswith("lockg:add:"):
        _, _, group_id_str, role_id_str, lock_group_id_str = data.split(":", 4)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        lock_group_id = int(lock_group_id_str)
        team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
        storage.add_team_role_to_lock_group(lock_group_id, team_role_id)
        await query.edit_message_text(
            _lock_groups_text(storage, group_id, role_id),
            reply_markup=_lock_groups_keyboard(storage, group_id, role_id),
        )
        await query.answer("Роль добавлена в lock-group")
        return True
    if data.startswith("lockg:remove:"):
        _, _, group_id_str, role_id_str, lock_group_id_str = data.split(":", 4)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        lock_group_id = int(lock_group_id_str)
        team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
        storage.remove_team_role_from_lock_group(lock_group_id, team_role_id)
        await query.edit_message_text(
            _lock_groups_text(storage, group_id, role_id),
            reply_markup=_lock_groups_keyboard(storage, group_id, role_id),
        )
        await query.answer("Роль удалена из lock-group")
        return True
    return False


async def _handle_add_role(query: CallbackQuery, data: str, context: ContextTypes.DEFAULT_TYPE, storage: Storage, runtime: RuntimeContext) -> bool:
    if data.startswith("addrole:"):
        group_id = int(data.split(":", 1)[1])
        master_roles = list_active_master_role_names(runtime)
        keyboard: list[list[InlineKeyboardButton]] = []
        for role_name in master_roles:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text=f"@{role_name}",
                        callback_data=f"addrole_master_name:{group_id}:{role_name}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")])
        await query.edit_message_text(
            "Выбери master-role для добавления в команду:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("addrole_master_name:"):
        _, group_id_str, role_name = data.split(":", 2)
        group_id = int(group_id_str)
        bound_role_name, created = bind_master_role_to_group(runtime, storage, group_id=group_id, role_name=role_name)
        note = "добавлена в" if created else "уже есть в"
        await query.edit_message_text(
            f"Роль @{bound_role_name} {note} группе {group_id}.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")]]
            ),
        )
        await query.answer()
        return True
    if data.startswith("addrole_copy:") or data.startswith("addrole_srcgrp:") or data.startswith("addrole_srcrole:") or data.startswith("addrole_create:"):
        group_id = int(data.split(":")[1])
        await query.edit_message_text(
            "Этот сценарий больше не используется в /groups. Используй добавление из списка master-role.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole:{group_id}")]]
            ),
        )
        await query.answer()
        return True
    return False


async def _handle_action(query: CallbackQuery, data: str, context: ContextTypes.DEFAULT_TYPE, storage: Storage, runtime: RuntimeContext) -> bool:
    if not data.startswith("act:"):
        return False
    _, action, group_id_str, role_id_str = data.split(":", 3)
    group_id = int(group_id_str)
    role_id = int(role_id_str)
    team_id = resolve_team_id(storage, group_id)
    role = storage.get_role_by_id(role_id)
    group_role = storage.get_team_role(team_id, role_id)
    pending_prompts, pending_roles = _resolve_pending_maps(context, runtime)
    provider_models, provider_model_map, provider_registry = _resolve_provider_data(context, runtime)
    if action == "toggle_enabled":
        result = execute_role_action(
            storage,
            RoleActionRequest(action="toggle_enabled", group_id=group_id, role_id=role_id),
        )
        if result.is_error or result.value is None:
            log_structured_error(
                logger,
                event="callback_toggle_enabled_failed",
                error=result.error,
                extra={"group_id": group_id, "role_id": role_id, "user_id": query.from_user.id},
            )
            await query.edit_message_text(
                to_telegram_message(result.error, "Не удалось изменить статус роли."),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        updated = result.value.state
        logger.info(
            "group_role toggle_enabled group_id=%s role_id=%s role=%s enabled=%s mode=%s actor_user_id=%s",
            group_id,
            role_id,
            _role_public_name(storage, group_id, role_id),
            updated.enabled,
            updated.mode,
            query.from_user.id,
        )
        note = "Роль включена." if updated.enabled else "Роль отключена."
        if not updated.enabled and updated.mode == "orchestrator":
            note = f"{note} Оркестратор неактивен до повторного включения."
        await query.edit_message_text(
            f"{note}\n\nРоль @{_role_public_name(storage, group_id, role_id)} "
            f"(enabled={'yes' if updated.enabled else 'no'}, mode={updated.mode}). Выбери действие:",
            reply_markup=_role_actions_keyboard(
                group_id,
                role_id,
                enabled=updated.enabled,
                mode=updated.mode,
            ),
        )
        await query.answer()
        return True
    if action == "set_mode_orchestrator":
        result = execute_role_action(
            storage,
            RoleActionRequest(action="set_mode_orchestrator", group_id=group_id, role_id=role_id),
        )
        if result.is_error or result.value is None:
            log_structured_error(
                logger,
                event="callback_set_mode_orchestrator_failed",
                error=result.error,
                extra={"group_id": group_id, "role_id": role_id, "user_id": query.from_user.id},
            )
            await query.edit_message_text(
                to_telegram_message(result.error, "Не удалось изменить режим роли."),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        updated = result.value.state
        previous_orchestrator_role_id = result.value.previous_orchestrator_role_id
        logger.info(
            "group_role set_mode group_id=%s role_id=%s role=%s mode=%s actor_user_id=%s previous_orchestrator_role_id=%s",
            group_id,
            role_id,
            _role_public_name(storage, group_id, role_id),
            updated.mode,
            query.from_user.id,
            previous_orchestrator_role_id,
        )
        note = "Роль назначена оркестратором."
        if previous_orchestrator_role_id is not None and previous_orchestrator_role_id != role_id:
            note = (
                f"{note}\nПредыдущий оркестратор "
                f"@{_role_public_name(storage, group_id, previous_orchestrator_role_id)} переведен в normal."
            )
        await query.edit_message_text(
            f"{note}\n\nРоль @{_role_public_name(storage, group_id, role_id)} "
            f"(enabled={'yes' if updated.enabled else 'no'}, mode={updated.mode}). Выбери действие:",
            reply_markup=_role_actions_keyboard(
                group_id,
                role_id,
                enabled=updated.enabled,
                mode=updated.mode,
            ),
        )
        await query.answer()
        return True
    if action == "set_mode_normal":
        result = execute_role_action(
            storage,
            RoleActionRequest(action="set_mode_normal", group_id=group_id, role_id=role_id),
        )
        if result.is_error or result.value is None:
            log_structured_error(
                logger,
                event="callback_set_mode_normal_failed",
                error=result.error,
                extra={"group_id": group_id, "role_id": role_id, "user_id": query.from_user.id},
            )
            await query.edit_message_text(
                to_telegram_message(result.error, "Не удалось изменить режим роли."),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        updated = result.value.state
        logger.info(
            "group_role set_mode group_id=%s role_id=%s role=%s mode=%s actor_user_id=%s",
            group_id,
            role_id,
            _role_public_name(storage, group_id, role_id),
            updated.mode,
            query.from_user.id,
        )
        await query.edit_message_text(
            f"Роль переведена в normal.\n\nРоль @{_role_public_name(storage, group_id, role_id)} "
            f"(enabled={'yes' if updated.enabled else 'no'}, mode={updated.mode}). Выбери действие:",
            reply_markup=_role_actions_keyboard(
                group_id,
                role_id,
                enabled=updated.enabled,
                mode=updated.mode,
            ),
        )
        await query.answer()
        return True
    if action == "set_prompt":
        if group_role.system_prompt_override is not None:
            prompt = group_role.system_prompt_override
        else:
            prompt = role.base_system_prompt
        if not prompt:
            prompt = "(не задано)"
        pending_prompts[query.from_user.id] = (group_id, role_id)
        await query.edit_message_text(
            "Ваш системный промпт сейчас такой:\n\n"
            f"{prompt}\n\n"
            "Хотите ввести новый? Напишите его следующим сообщением (или 'clear', чтобы удалить).",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_prompt:{group_id}:{role_id}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                ]
            ),
        )
        await query.answer()
        return True
    if action == "master_defaults":
        await query.edit_message_text(
            _master_defaults_text(runtime, role_id),
            reply_markup=_master_defaults_keyboard(group_id, role_id),
        )
        await query.answer()
        return True
    if action == "master_set_prompt":
        pending_roles[query.from_user.id] = {
            "mode": "master_update",
            "step": "master_prompt",
            "role_id": role_id,
            "target_group_id": group_id,
        }
        await query.edit_message_text(
            "Отправь новый system prompt для master-role в личном сообщении.\nЛимит: 16000 символов.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "master_set_suffix":
        pending_roles[query.from_user.id] = {
            "mode": "master_update",
            "step": "master_suffix",
            "role_id": role_id,
            "target_group_id": group_id,
        }
        await query.edit_message_text(
            "Отправь новую instruction для master-role в личном сообщении.\nЛимит: 8000 символов.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "master_set_model":
        role_for_master = storage.get_role_by_id(role_id)
        current_model = role_for_master.llm_model
        if not current_model:
            current_label = "(не задана)"
        elif current_model in provider_model_map:
            current_obj = provider_model_map.get(current_model)
            current_provider = provider_registry.get(current_obj.provider_id) if current_obj else None
            current_label = model_label(current_obj, current_provider) if current_obj else current_model
        else:
            current_label = f"{current_model} (недоступна)"
        if not provider_models:
            await query.edit_message_text(
                "Список моделей не настроен в llm_providers.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        buttons = []
        for model in provider_models:
            provider = provider_registry.get(model.provider_id)
            label = model_label(model, provider)
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"msetmodel:{group_id}:{role_id}:{model.full_id}")]
            )
        buttons.append([InlineKeyboardButton(text="Сбросить (None)", callback_data=f"msetmodel:{group_id}:{role_id}:__none__")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")])
        await query.edit_message_text(
            f"Текущая master-модель: {current_label}\n\nВыбери новую модель:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer()
        return True
    if action == "master_clear_prompt":
        role_for_master = storage.get_role_by_id(role_id)
        update_master_role_json(
            runtime=runtime,
            storage=storage,
            role_name=role_for_master.role_name,
            base_system_prompt="",
        )
        _log_master_role_updated(
            user_id=query.from_user.id,
            role_name=role_for_master.role_name,
            changed_fields=["base_system_prompt"],
            operation="clear",
            source="callback",
        )
        await query.edit_message_text(
            _master_defaults_text(runtime, role_id),
            reply_markup=_master_defaults_keyboard(group_id, role_id),
        )
        await query.answer("Master system prompt очищен")
        return True
    if action == "master_clear_suffix":
        role_for_master = storage.get_role_by_id(role_id)
        update_master_role_json(
            runtime=runtime,
            storage=storage,
            role_name=role_for_master.role_name,
            extra_instruction="",
        )
        _log_master_role_updated(
            user_id=query.from_user.id,
            role_name=role_for_master.role_name,
            changed_fields=["extra_instruction"],
            operation="clear",
            source="callback",
        )
        await query.edit_message_text(
            _master_defaults_text(runtime, role_id),
            reply_markup=_master_defaults_keyboard(group_id, role_id),
        )
        await query.answer("Master instruction очищена")
        return True
    if action == "master_clear_model":
        role_for_master = storage.get_role_by_id(role_id)
        update_master_role_json(
            runtime=runtime,
            storage=storage,
            role_name=role_for_master.role_name,
            llm_model=None,
        )
        _log_master_role_updated(
            user_id=query.from_user.id,
            role_name=role_for_master.role_name,
            changed_fields=["llm_model"],
            operation="clear",
            source="callback",
        )
        await query.edit_message_text(
            _master_defaults_text(runtime, role_id),
            reply_markup=_master_defaults_keyboard(group_id, role_id),
        )
        await query.answer("Master модель сброшена")
        return True
    if action == "prepost_processing":
        await query.edit_message_text(
            f"Pre/Post Processing для роли @{_role_public_name(storage, group_id, role_id)}:",
            reply_markup=_role_prepost_processing_keyboard(runtime, storage, group_id, role_id),
        )
        await query.answer()
        return True
    if action == "skills":
        await query.edit_message_text(
            f"Skills для роли @{_role_public_name(storage, group_id, role_id)}:",
            reply_markup=_role_skills_keyboard(runtime, storage, group_id, role_id),
        )
        await query.answer()
        return True
    if action == "clear_prompt":
        clear_team_role_prompt(storage, group_id=group_id, role_id=role_id)
        await query.edit_message_text(
            "Системный промпт очищен.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "rename_role":
        pending_roles[query.from_user.id] = {
            "mode": "rename",
            "step": "name",
            "target_group_id": group_id,
            "role_id": role_id,
        }
        await query.edit_message_text(
            f"Отправь новое имя для роли @{_role_public_name(storage, group_id, role_id)} "
            "(латиница, цифры, underscore).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "set_model":
        current_model = resolve_provider_model(
            provider_models,
            provider_model_map,
            provider_registry,
            group_role.model_override,
        )
        current_model_label = current_model
        current_model_obj = provider_model_map.get(current_model)
        if current_model_obj:
            current_provider = provider_registry.get(current_model_obj.provider_id)
            current_model_label = model_label(current_model_obj, current_provider)
        if not provider_models:
            await query.edit_message_text(
                "Список моделей не настроен в llm_providers.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        buttons = []
        for model in provider_models:
            provider = provider_registry.get(model.provider_id)
            label = model_label(model, provider)
            buttons.append(
                [InlineKeyboardButton(text=label, callback_data=f"setmodel:{group_id}:{role_id}:{model.full_id}")]
            )
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")])
        await query.edit_message_text(
            f"Текущая модель: {current_model_label}\n\nВыбери модель:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer()
        return True
    if action == "lock_groups":
        await query.edit_message_text(
            _lock_groups_text(storage, group_id, role_id),
            reply_markup=_lock_groups_keyboard(storage, group_id, role_id),
        )
        await query.answer()
        return True
    if action == "set_suffix":
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "suffix",
            "step": "suffix",
            "target_group_id": group_id,
            "role_id": role_id,
        }
        current_suffix = group_role.user_prompt_suffix or "(не задано)"
        text = (
            "Эта инструкция будет добавляться перед каждым сообщением пользователя и уходить в LLM одним сообщением.\n\n"
            "Текущая инструкция к сообщениям:\n\n"
            f"{current_suffix}\n\n"
            "Хотите изменить? Отправьте новую инструкцию (или 'clear' чтобы убрать)."
        )
        chunks = list(split_message(text))
        await query.edit_message_text(
            chunks[0],
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_suffix:{group_id}:{role_id}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                ]
            ),
        )
        for extra in chunks[1:]:
            await context.bot.send_message(chat_id=query.message.chat.id, text=extra)
        await query.answer()
        return True
    if action == "clear_suffix":
        clear_team_role_suffix(storage, group_id=group_id, role_id=role_id)
        await query.edit_message_text(
            "Инструкция к сообщениям очищена.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "set_reply_prefix":
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "reply_prefix",
            "step": "reply_prefix",
            "target_group_id": group_id,
            "role_id": role_id,
        }
        current_prefix = group_role.user_reply_prefix or "(не задано)"
        text = (
            "Эта инструкция будет добавляться перед текстом сообщения, на которое пользователь отвечает.\n\n"
            "Текущая инструкция для реплаев:\n\n"
            f"{current_prefix}\n\n"
            "Хотите изменить? Отправьте новую инструкцию (или 'clear' чтобы убрать)."
        )
        chunks = list(split_message(text))
        await query.edit_message_text(
            chunks[0],
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text="🧹 Очистить", callback_data=f"act:clear_reply_prefix:{group_id}:{role_id}")],
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")],
                ]
            ),
        )
        for extra in chunks[1:]:
            await context.bot.send_message(chat_id=query.message.chat.id, text=extra)
        await query.answer()
        return True
    if action == "clear_reply_prefix":
        clear_team_role_reply_prefix(storage, group_id=group_id, role_id=role_id)
        await query.edit_message_text(
            "Инструкция для реплаев очищена.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "reset_session":
        role_name = reset_team_role_session(runtime, storage, group_id=group_id, role_id=role_id, user_id=query.from_user.id)
        await query.edit_message_text(
            f"Сессия для роли @{role_name} в группе {group_id} сброшена.",
        )
        await query.answer()
        return True
    if action == "delete_role":
        role_name = delete_team_role_binding(runtime, storage, group_id=group_id, role_id=role_id, user_id=query.from_user.id)
        await query.edit_message_text(
            f"Роль @{role_name} удалена из группы {group_id}.",
        )
        await query.answer()
        return True
    return False


async def _handle_prepost_processing_toggle(
    query: CallbackQuery,
    data: str,
    storage: Storage,
    runtime: RuntimeContext,
) -> bool:
    if not data.startswith("pptoggle:"):
        return False
    _, group_id_str, role_id_str, prepost_processing_id = data.split(":", 3)
    group_id = int(group_id_str)
    role_id = int(role_id_str)
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    if runtime.prepost_processing_registry.get(prepost_processing_id) is None:
        await query.edit_message_text(
            f"Pre/Post Processing {prepost_processing_id} не найден в реестре.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    current = storage.get_role_prepost_processing_for_team_role(team_role_id, prepost_processing_id)
    if current is None:
        storage.upsert_role_prepost_processing_for_team_role(team_role_id, prepost_processing_id, enabled=True, config=None)
        state_note = f"Pre/Post Processing {prepost_processing_id} включен."
    else:
        storage.set_role_prepost_processing_enabled_for_team_role(team_role_id, prepost_processing_id, not current.enabled)
        state_note = f"Pre/Post Processing {prepost_processing_id} {'включен' if not current.enabled else 'выключен'}."
    await query.edit_message_text(
        f"{state_note}\n\nPre/Post Processing для роли @{_role_public_name(storage, group_id, role_id)}:",
        reply_markup=_role_prepost_processing_keyboard(runtime, storage, group_id, role_id),
    )
    await query.answer()
    return True


async def _handle_skill_toggle(
    query: CallbackQuery,
    data: str,
    storage: Storage,
    runtime: RuntimeContext,
) -> bool:
    if not data.startswith("sktoggle:"):
        return False
    _, group_id_str, role_id_str, skill_id = data.split(":", 3)
    group_id = int(group_id_str)
    role_id = int(role_id_str)
    team_role_id = _team_role_id(storage, group_id, role_id, ensure_exists=True)
    if runtime.skills_registry.get(skill_id) is None:
        await query.edit_message_text(
            f"Skill {skill_id} не найден в реестре.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    current = storage.get_role_skill_for_team_role(team_role_id, skill_id)
    if current is None:
        storage.upsert_role_skill_for_team_role(team_role_id, skill_id, enabled=True, config=None)
        state_note = f"Skill {skill_id} включен."
    else:
        storage.set_role_skill_enabled_for_team_role(team_role_id, skill_id, not current.enabled)
        state_note = f"Skill {skill_id} {'включен' if not current.enabled else 'выключен'}."
    await query.edit_message_text(
        f"{state_note}\n\nSkills для роли @{_role_public_name(storage, group_id, role_id)}:",
        reply_markup=_role_skills_keyboard(runtime, storage, group_id, role_id),
    )
    await query.answer()
    return True


async def _handle_set_model(
    query: CallbackQuery,
    data: str,
    storage: Storage,
    runtime: RuntimeContext,
    *,
    provider_model_map: dict[str, object],
    provider_registry: dict[str, object],
) -> bool:
    if data.startswith("msetmodel:"):
        _, group_id_str, role_id_str, model_name = data.split(":", 3)
        group_id = int(group_id_str)
        role_id = int(role_id_str)
        if model_name != "__none__" and model_name not in provider_model_map:
            await query.edit_message_text(
                "Модель не найдена в llm_providers.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")]]
                ),
            )
            await query.answer()
            return True
        role = storage.get_role_by_id(role_id)
        new_model = None if model_name == "__none__" else model_name
        update_master_role_json(
            runtime=runtime,
            storage=storage,
            role_name=role.role_name,
            llm_model=new_model,
        )
        _log_master_role_updated(
            user_id=query.from_user.id,
            role_name=role.role_name,
            changed_fields=["llm_model"],
            operation="set",
            source="callback",
        )
        label = "(не задана)"
        if new_model:
            model_obj = provider_model_map.get(new_model)
            provider = provider_registry.get(model_obj.provider_id) if model_obj else None
            label = model_label(model_obj, provider) if model_obj else new_model
        await query.edit_message_text(
            f"Master-модель для @{role.role_name} обновлена: {label}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"act:master_defaults:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if not data.startswith("setmodel:"):
        return False
    _, group_id_str, role_id_str, model_name = data.split(":", 3)
    group_id = int(group_id_str)
    role_id = int(role_id_str)
    if model_name not in provider_model_map:
        await query.edit_message_text(
            "Модель не найдена в llm_providers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    set_team_role_model(storage, group_id=group_id, role_id=role_id, model_name=model_name)
    model_obj = provider_model_map.get(model_name)
    label = model_name
    if model_obj:
        provider = provider_registry.get(model_obj.provider_id)
        label = model_label(model_obj, provider)
    await query.edit_message_text(
        f"Модель для роли обновлена: {label}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
        ),
    )
    await query.answer()
    return True


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if not await _is_owner_callback(query, runtime):
        return

    storage: Storage = _resolve_storage(context, runtime)
    pending_prompts, pending_role_ops = _resolve_pending_maps(context, runtime)
    _, provider_model_map, provider_registry = _resolve_provider_data(context, runtime)
    data = query.data or ""
    if data.startswith("mrole") or data.startswith("mroles"):
        refresh_role_catalog(runtime=runtime, storage=storage)
    if not data.startswith("mrole_create_model:"):
        pending_prompts.pop(query.from_user.id, None)
        pending_role_ops.pop(query.from_user.id, None)

    if await _handle_groups_navigation(query, data, storage):
        return
    if await _handle_master_roles_navigation(query, data, storage, runtime):
        return
    if await _handle_master_role_create_model(query, data, storage, runtime):
        return
    if await _handle_add_role(query, data, context, storage, runtime):
        return
    if await _handle_lock_groups(query, data, storage):
        return
    if await _handle_action(query, data, context, storage, runtime):
        return
    if await _handle_prepost_processing_toggle(query, data, storage, runtime):
        return
    if await _handle_skill_toggle(query, data, storage, runtime):
        return
    if await _handle_set_model(
        query,
        data,
        storage,
        runtime,
        provider_model_map=provider_model_map,
        provider_registry=provider_registry,
    ):
        return
