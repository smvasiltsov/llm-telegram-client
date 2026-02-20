from __future__ import annotations

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.llm_providers import model_label
from app.runtime import RuntimeContext
from app.services.prompt_builder import provider_id_from_model, resolve_provider_model
from app.storage import Storage
from app.utils import split_message


async def _handle_groups_navigation(query: CallbackQuery, data: str, storage: Storage) -> bool:
    if data.startswith("grp:"):
        group_id = int(data.split(":", 1)[1])
        roles = storage.list_roles_for_group(group_id)
        keyboard = [
            [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"role:{group_id}:{role.role_id}")]
            for role in roles
        ]
        keyboard.append([InlineKeyboardButton(text="➕ Добавить роль", callback_data=f"addrole:{group_id}")])
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back:groups")])
        await query.edit_message_text(
            f"Роли группы {group_id}:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data == "back:groups":
        groups = storage.list_groups()
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
        role = storage.get_role_by_id(role_id)
        keyboard = [
            [InlineKeyboardButton(text="Системный промпт", callback_data=f"act:set_prompt:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Инструкция к сообщениям", callback_data=f"act:set_suffix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Инструкция для реплаев", callback_data=f"act:set_reply_prefix:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="LLM-модель", callback_data=f"act:set_model:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Переименовать роль", callback_data=f"act:rename_role:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Сбросить сессию", callback_data=f"act:reset_session:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="Удалить роль", callback_data=f"act:delete_role:{group_id}:{role_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")],
        ]
        await query.edit_message_text(
            f"Роль @{role.role_name}. Выбери действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    return False


async def _handle_add_role(query: CallbackQuery, data: str, context: ContextTypes.DEFAULT_TYPE, storage: Storage, runtime: RuntimeContext) -> bool:
    if data.startswith("addrole:"):
        group_id = int(data.split(":", 1)[1])
        keyboard = [
            [InlineKeyboardButton(text="Скопировать роль", callback_data=f"addrole_copy:{group_id}")],
            [InlineKeyboardButton(text="Создать новую", callback_data=f"addrole_create:{group_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{group_id}")],
        ]
        await query.edit_message_text(
            "Как добавить роль?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("addrole_copy:"):
        target_group_id = int(data.split(":", 1)[1])
        groups = storage.list_groups()
        keyboard = [
            [InlineKeyboardButton(text=(group.title or str(group.group_id)), callback_data=f"addrole_srcgrp:{target_group_id}:{group.group_id}")]
            for group in groups
        ]
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole:{target_group_id}")])
        await query.edit_message_text(
            "Выбери группу-источник:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("addrole_srcgrp:"):
        _, target_group_id_str, source_group_id_str = data.split(":", 2)
        target_group_id = int(target_group_id_str)
        source_group_id = int(source_group_id_str)
        roles = storage.list_roles_for_group(source_group_id)
        keyboard = [
            [InlineKeyboardButton(text=f"@{role.role_name}", callback_data=f"addrole_srcrole:{target_group_id}:{source_group_id}:{role.role_id}")]
            for role in roles
        ]
        keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole_copy:{target_group_id}")])
        await query.edit_message_text(
            "Выбери роль для копирования:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        await query.answer()
        return True
    if data.startswith("addrole_srcrole:"):
        _, target_group_id_str, source_group_id_str, role_id_str = data.split(":", 3)
        target_group_id = int(target_group_id_str)
        source_group_id = int(source_group_id_str)
        role_id = int(role_id_str)
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "clone",
            "step": "name",
            "target_group_id": target_group_id,
            "source_group_id": source_group_id,
            "source_role_id": role_id,
        }
        role = storage.get_role_by_id(role_id)
        await query.edit_message_text(
            f"Отправь новое имя роли для копии @{role.role_name}.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"addrole_copy:{target_group_id}")]]
            ),
        )
        await query.answer()
        return True
    if data.startswith("addrole_create:"):
        group_id = int(data.split(":", 1)[1])
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "create",
            "step": "name",
            "target_group_id": group_id,
        }
        await query.edit_message_text(
            "Отправь имя новой роли (латиница, цифры, underscore).",
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
    role = storage.get_role_by_id(role_id)
    if action == "set_prompt":
        group_role = storage.get_group_role(group_id, role_id)
        if group_role.system_prompt_override is not None:
            prompt = group_role.system_prompt_override
        else:
            prompt = role.base_system_prompt
        if not prompt:
            prompt = "(не задано)"
        pending_prompts = runtime.pending_prompts
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
    if action == "clear_prompt":
        storage.set_group_role_prompt(group_id, role_id, "")
        await query.edit_message_text(
            "Системный промпт очищен.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "rename_role":
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "rename",
            "step": "name",
            "target_group_id": group_id,
            "role_id": role_id,
        }
        await query.edit_message_text(
            f"Отправь новое имя для роли @{role.role_name} (латиница, цифры, underscore).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "set_model":
        group_role = storage.get_group_role(group_id, role_id)
        provider_models = runtime.provider_models
        provider_model_map = runtime.provider_model_map
        provider_registry = runtime.provider_registry
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
    if action == "set_suffix":
        pending_roles = runtime.pending_role_ops
        pending_roles[query.from_user.id] = {
            "mode": "suffix",
            "step": "suffix",
            "target_group_id": group_id,
            "role_id": role_id,
        }
        group_role = storage.get_group_role(group_id, role_id)
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
        storage.set_group_role_user_prompt_suffix(group_id, role_id, None)
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
        group_role = storage.get_group_role(group_id, role_id)
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
        storage.set_group_role_user_reply_prefix(group_id, role_id, None)
        await query.edit_message_text(
            "Инструкция для реплаев очищена.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    if action == "reset_session":
        storage.delete_user_role_session(query.from_user.id, group_id, role_id)
        provider_registry = runtime.provider_registry
        default_provider_id = runtime.default_provider_id
        group_role = storage.get_group_role(group_id, role_id)
        model_override = group_role.model_override or role.llm_model
        provider_id = provider_id_from_model(model_override, default_provider_id, provider_registry)
        provider = provider_registry.get(provider_id)
        if provider:
            for field in provider.user_fields.values():
                if field.scope == "role":
                    storage.delete_provider_user_value(provider_id, field.key, role_id)
        await query.edit_message_text(
            f"Сессия для роли @{role.role_name} в группе {group_id} сброшена.",
        )
        await query.answer()
        return True
    if action == "delete_role":
        storage.deactivate_group_role(group_id, role_id)
        storage.delete_user_role_session(query.from_user.id, group_id, role_id)
        storage.delete_role_if_unused(role_id)
        await query.edit_message_text(
            f"Роль @{role.role_name} удалена из группы {group_id}.",
        )
        await query.answer()
        return True
    return False


async def _handle_set_model(query: CallbackQuery, data: str, storage: Storage, runtime: RuntimeContext) -> bool:
    if not data.startswith("setmodel:"):
        return False
    _, group_id_str, role_id_str, model_name = data.split(":", 3)
    group_id = int(group_id_str)
    role_id = int(role_id_str)
    provider_model_map = runtime.provider_model_map
    if model_name not in provider_model_map:
        await query.edit_message_text(
            "Модель не найдена в llm_providers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"role:{group_id}:{role_id}")]]
            ),
        )
        await query.answer()
        return True
    storage.set_group_role_model(group_id, role_id, model_name)
    provider_registry = runtime.provider_registry
    provider_model_map = runtime.provider_model_map
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


async def _handle_add_role_model(query: CallbackQuery, data: str, storage: Storage, runtime: RuntimeContext) -> bool:
    if not data.startswith("addrole_model:"):
        return False
    model_name = data.split(":", 1)[1]
    pending_roles = runtime.pending_role_ops
    state = pending_roles.get(query.from_user.id)
    if not state or state.get("step") != "model_select":
        await query.answer()
        return True
    provider_model_map = runtime.provider_model_map
    if model_name != "__skip__" and model_name not in provider_model_map:
        await query.edit_message_text(
            "Модель не найдена в llm_providers.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{state['target_group_id']}")]]
            ),
        )
        await query.answer()
        return True
    model = None if model_name == "__skip__" else model_name
    target_group_id = state["target_group_id"]
    role_name = state["role_name"]
    prompt = state["prompt"]
    if state["mode"] == "create":
        role = storage.upsert_role(
            role_name=role_name,
            description=f"Роль {role_name}",
            base_system_prompt=prompt,
            extra_instruction="",
            llm_model=model,
            is_active=True,
        )
    else:
        source_role = storage.get_role_by_id(state["source_role_id"])
        role = storage.upsert_role(
            role_name=role_name,
            description=source_role.description,
            base_system_prompt=source_role.base_system_prompt,
            extra_instruction=source_role.extra_instruction,
            llm_model=source_role.llm_model,
            is_active=True,
        )
    storage.ensure_group_role(target_group_id, role.role_id)
    if model is not None:
        storage.set_group_role_model(target_group_id, role.role_id, model)
    pending_roles.pop(query.from_user.id, None)
    await query.edit_message_text(
        f"Роль @{role.role_name} добавлена в группу {target_group_id}.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"grp:{target_group_id}")]]
        ),
    )
    await query.answer()
    return True


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user:
        return

    runtime: RuntimeContext = context.application.bot_data["runtime"]
    if query.from_user.id != runtime.owner_user_id:
        await query.answer()
        return

    storage: Storage = runtime.storage
    data = query.data or ""
    if not data.startswith("addrole_model:"):
        runtime.pending_prompts.pop(query.from_user.id, None)
        runtime.pending_role_ops.pop(query.from_user.id, None)

    if await _handle_groups_navigation(query, data, storage):
        return
    if await _handle_add_role(query, data, context, storage, runtime):
        return
    if await _handle_action(query, data, context, storage, runtime):
        return
    if await _handle_set_model(query, data, storage, runtime):
        return
    if await _handle_add_role_model(query, data, storage, runtime):
        return
