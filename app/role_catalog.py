from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ROLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
FILE_ROLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class CatalogRole:
    role_name: str
    description: str
    base_system_prompt: str
    extra_instruction: str
    llm_model: str | None
    is_active: bool
    source_path: Path


@dataclass(frozen=True)
class CatalogIssue:
    path: Path
    reason: str


@dataclass
class RoleCatalog:
    root_dir: Path
    roles_by_name: dict[str, CatalogRole]
    issues: list[CatalogIssue]

    @classmethod
    def load(cls, root_dir: str | Path) -> "RoleCatalog":
        root = Path(root_dir)
        root.mkdir(parents=True, exist_ok=True)
        roles_by_name: dict[str, CatalogRole] = {}
        issues: list[CatalogIssue] = []
        seen_file_role_names: dict[str, Path] = {}

        for path in sorted(root.glob("*.json")):
            file_role_name = path.stem.strip()
            casefold_name = file_role_name.lower()
            winner = seen_file_role_names.get(casefold_name)
            if winner is not None:
                issues.append(
                    CatalogIssue(
                        path=path,
                        reason=f"duplicate_role_name_casefold:{casefold_name}:winner={winner.name}",
                    )
                )
                continue
            seen_file_role_names[casefold_name] = path

            if not file_role_name or not FILE_ROLE_NAME_RE.match(file_role_name):
                issues.append(CatalogIssue(path=path, reason=f"invalid_file_name:{file_role_name or '<empty>'}"))
                continue

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(CatalogIssue(path=path, reason=f"invalid_json: {exc}"))
                continue

            validated = _validate_role_payload(data, file_role_name=file_role_name)
            if isinstance(validated, str):
                issues.append(CatalogIssue(path=path, reason=validated))
                continue

            role_name = casefold_name
            if role_name in roles_by_name:
                issues.append(CatalogIssue(path=path, reason=f"duplicate_role_name_from_file:{role_name}"))
                continue
            mismatch = validated.get("role_name_mismatch")
            if isinstance(mismatch, str) and mismatch:
                issues.append(CatalogIssue(path=path, reason=mismatch))

            roles_by_name[role_name] = CatalogRole(
                role_name=role_name,
                description=validated["description"],
                base_system_prompt=validated["base_system_prompt"],
                extra_instruction=validated["extra_instruction"],
                llm_model=validated["llm_model"],
                is_active=validated["is_active"],
                source_path=path,
            )

        return cls(root_dir=root.resolve(), roles_by_name=roles_by_name, issues=issues)

    def get(self, role_name: str) -> CatalogRole | None:
        return self.roles_by_name.get(str(role_name).strip().lower())

    def list_all(self) -> list[CatalogRole]:
        return sorted(self.roles_by_name.values(), key=lambda x: x.role_name)

    def list_active(self) -> list[CatalogRole]:
        return [item for item in self.list_all() if item.is_active]


def _validate_role_payload(data: object, *, file_role_name: str) -> dict[str, object] | str:
    if not isinstance(data, dict):
        return "payload_not_object"

    schema_version = data.get("schema_version", 1)
    if schema_version != 1:
        return "unsupported_schema_version"

    role_name_meta = _pick_field(data, "role_name", aliases=())
    if role_name_meta is not None:
        if not isinstance(role_name_meta, str):
            return "invalid_role_name"
        role_name_meta = role_name_meta.strip()
        if role_name_meta and not ROLE_NAME_RE.match(role_name_meta):
            return "invalid_role_name"
    role_name_mismatch = ""
    if isinstance(role_name_meta, str) and role_name_meta and role_name_meta.lower() != file_role_name:
        role_name_mismatch = f"role_name_mismatch:{role_name_meta}->{file_role_name}"

    base_system_prompt_raw = _pick_field(data, "base_system_prompt", aliases=("system_prompt", "prompt"))
    if base_system_prompt_raw is None:
        return "missing_field:base_system_prompt"
    if not isinstance(base_system_prompt_raw, str):
        return "invalid_base_system_prompt"

    extra_instruction_raw = _pick_field(data, "extra_instruction", aliases=("instruction",))
    if extra_instruction_raw is None:
        extra_instruction_raw = ""
    if not isinstance(extra_instruction_raw, str):
        return "invalid_extra_instruction"

    description_raw = _pick_field(data, "description", aliases=("summary",))
    if description_raw is None:
        description_raw = ""
    if not isinstance(description_raw, str):
        return "invalid_description"

    llm_model_raw = _pick_field(data, "llm_model", aliases=("model",))
    if llm_model_raw is None:
        llm_model: str | None = None
    elif isinstance(llm_model_raw, str):
        llm_model = llm_model_raw.strip() or None
    else:
        return "invalid_llm_model"

    is_active_raw = _pick_field(data, "is_active", aliases=("active", "enabled"))
    if is_active_raw is None:
        is_active_raw = True
    if not isinstance(is_active_raw, bool):
        return "invalid_is_active"

    return {
        "description": description_raw,
        "base_system_prompt": base_system_prompt_raw,
        "extra_instruction": extra_instruction_raw,
        "llm_model": llm_model,
        "is_active": is_active_raw,
        "role_name_mismatch": role_name_mismatch,
    }


def _pick_field(data: dict[str, object], key: str, *, aliases: tuple[str, ...]) -> object | None:
    if key in data:
        return data[key]
    for alias in aliases:
        if alias in data:
            return data[alias]
    return None
