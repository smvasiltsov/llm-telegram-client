from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.role_catalog import RoleCatalog
from app.storage import Storage

if TYPE_CHECKING:
    from app.runtime import RuntimeContext

logger = logging.getLogger("bot")


def create_master_role_json(
    *,
    runtime: "RuntimeContext",
    storage: Storage,
    role_name: str,
    base_system_prompt: str,
    extra_instruction: str,
    llm_model: str | None,
) -> int:
    root = runtime.role_catalog.root_dir
    role_path = root / f"{role_name}.json"
    if role_path.exists():
        raise ValueError(f"Master-role already exists in catalog: {role_name}")
    payload = {
        "schema_version": 1,
        "role_name": role_name,
        "description": f"Master role {role_name}",
        "base_system_prompt": base_system_prompt,
        "extra_instruction": extra_instruction,
        "llm_model": llm_model,
        "is_active": True,
    }
    role_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _reload_runtime_catalog(runtime, storage)
    role = ensure_role_identity_by_name(runtime=runtime, storage=storage, role_name=role_name)
    return role.role_id


def ensure_role_identity_by_name(*, runtime: "RuntimeContext", storage: Storage, role_name: str):
    try:
        return storage.get_role_by_name(role_name)
    except ValueError:
        catalog_role = runtime.role_catalog.get(role_name)
        if catalog_role is None:
            raise ValueError(f"Master-role not found in catalog: {role_name}")
        return storage.upsert_role(
            role_name=catalog_role.role_name,
            description=catalog_role.description,
            base_system_prompt=catalog_role.base_system_prompt,
            extra_instruction=catalog_role.extra_instruction,
            llm_model=catalog_role.llm_model,
            is_active=catalog_role.is_active,
        )


def list_active_master_role_names(runtime: "RuntimeContext") -> list[str]:
    return [item.role_name for item in runtime.role_catalog.list_active()]


def master_role_exists(runtime: "RuntimeContext", role_name: str) -> bool:
    return runtime.role_catalog.get(role_name) is not None


def refresh_role_catalog(*, runtime: "RuntimeContext", storage: Storage) -> None:
    _reload_runtime_catalog(runtime, storage)
    _log_catalog_issues(runtime)
    _deactivate_bindings_for_deleted_roles(runtime=runtime, storage=storage)


def _reload_runtime_catalog(runtime: "RuntimeContext", storage: Storage) -> None:
    root: Path = runtime.role_catalog.root_dir
    catalog = RoleCatalog.load(root)
    runtime.role_catalog = catalog
    storage.attach_role_catalog(catalog)


def _deactivate_bindings_for_deleted_roles(*, runtime: "RuntimeContext", storage: Storage) -> None:
    role_files = {item.role_name for item in runtime.role_catalog.list_all()}
    active_role_names = storage.list_active_team_role_names()
    missing_names = [name for name in active_role_names if name not in role_files]
    if not missing_names:
        return
    deactivated = 0
    for role_name in missing_names:
        deactivated += storage.deactivate_team_roles_by_role_name(role_name)
    if deactivated > 0:
        logger.info(
            "role catalog refresh deactivated missing role bindings: roles=%s deactivated=%s",
            ",".join(sorted(missing_names)),
            deactivated,
        )


def _log_catalog_issues(runtime: "RuntimeContext") -> None:
    issues = runtime.role_catalog.issues
    signature = tuple((item.path.name, item.reason) for item in issues)
    last_signature = getattr(runtime, "_last_role_catalog_issue_signature", None)
    if signature == last_signature:
        return
    setattr(runtime, "_last_role_catalog_issue_signature", signature)
    if not issues:
        logger.info("role catalog refresh: no issues")
        return
    logger.warning("role catalog refresh issues count=%s", len(issues))
    for issue in issues[:20]:
        logger.warning("role catalog issue path=%s reason=%s", issue.path, issue.reason)
    if len(issues) > 20:
        logger.warning("role catalog issue list truncated omitted=%s", len(issues) - 20)
