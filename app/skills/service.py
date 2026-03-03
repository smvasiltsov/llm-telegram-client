from __future__ import annotations

from typing import Any

from app.skills.registry import SkillRecord, SkillRegistry
from skills_sdk.contract import SkillSpec


class SkillService:
    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def list_specs(self) -> list[SkillSpec]:
        return self._registry.list_specs()

    def get(self, skill_id: str) -> SkillRecord | None:
        return self._registry.get(skill_id)

    def list_catalog(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec in sorted(self._registry.list_specs(), key=lambda item: item.skill_id):
            result.append(
                {
                    "skill_id": spec.skill_id,
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "mode": spec.mode,
                    "timeout_sec": spec.timeout_sec,
                }
            )
        return result
