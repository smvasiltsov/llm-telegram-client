from __future__ import annotations

from app.storage import Storage


DEFAULT_ROLES = [
    {
        "role_name": "analyst",
        "description": "Анализирует идеи, риски и метрики",
        "base_system_prompt": "Ты — аналитик продукта.",
        "extra_instruction": "Всегда пиши кратко, структурировано, с bullet points.",
        "llm_model": None,
        "is_active": True,
    },
    {
        "role_name": "critic",
        "description": "Ищет слабые места и критикует",
        "base_system_prompt": "Ты — критик.",
        "extra_instruction": "Укажи на слабые места и риски.",
        "llm_model": None,
        "is_active": True,
    },
]


def seed_roles(storage: Storage) -> None:
    for role in DEFAULT_ROLES:
        storage.upsert_role(
            role_name=role["role_name"],
            description=role["description"],
            base_system_prompt=role["base_system_prompt"],
            extra_instruction=role["extra_instruction"],
            llm_model=role["llm_model"],
            is_active=role["is_active"],
        )


def seed_group_roles(storage: Storage, group_id: int) -> None:
    for role in storage.list_active_roles():
        storage.ensure_group_role(group_id, role.role_id)
