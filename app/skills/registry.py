from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from skills_sdk.contract import SkillProtocol, SkillSpec


logger = logging.getLogger("skills_registry")


@dataclass(frozen=True)
class SkillRecord:
    manifest: dict[str, Any]
    instance: SkillProtocol
    spec: SkillSpec


class SkillRegistry:
    def __init__(self) -> None:
        self._records: dict[str, SkillRecord] = {}

    def list_specs(self) -> list[SkillSpec]:
        return [record.spec for record in self._records.values()]

    def get(self, skill_id: str) -> SkillRecord | None:
        return self._records.get(skill_id)

    def register(self, skill: SkillProtocol, manifest: dict[str, Any] | None = None) -> SkillRecord:
        spec = skill.describe()
        effective_manifest = manifest or {
            "id": spec.skill_id,
            "version": spec.version,
            "entrypoint": "<runtime>",
        }
        self._validate_skill(skill, effective_manifest)
        record = SkillRecord(
            manifest=dict(effective_manifest),
            instance=skill,
            spec=spec,
        )
        self._records[spec.skill_id] = record
        return record

    def discover(self, skills_dir: str | Path) -> None:
        base = Path(skills_dir)
        if not base.exists() or not base.is_dir():
            logger.info("skills directory not found: %s", base)
            return

        for skill_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            manifest_path = skill_dir / "skill.yaml"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._load_manifest(manifest_path)
                skill = self._load_entrypoint(skill_dir, manifest["entrypoint"])
                self._validate_skill(skill, manifest)
                spec = skill.describe()
                record = SkillRecord(
                    manifest=manifest,
                    instance=skill,
                    spec=spec,
                )
                self._records[spec.skill_id] = record
                logger.info(
                    "skill loaded id=%s version=%s path=%s",
                    spec.skill_id,
                    spec.version,
                    skill_dir,
                )
            except Exception:
                logger.exception("skill load failed path=%s", skill_dir)

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest must be object: {manifest_path}")
        required = ("id", "version", "entrypoint")
        missing = [key for key in required if not str(raw.get(key, "")).strip()]
        if missing:
            raise ValueError(f"Manifest missing required keys {missing}: {manifest_path}")
        return raw

    def _load_entrypoint(self, skill_dir: Path, entrypoint: str) -> SkillProtocol:
        if ":" not in entrypoint:
            raise ValueError(f"Invalid entrypoint '{entrypoint}', expected module:function")
        module_name, factory_name = entrypoint.split(":", 1)
        module_import = f"skills.{skill_dir.name}.{module_name}"
        module = importlib.import_module(module_import)
        factory = getattr(module, factory_name, None)
        if factory is None:
            raise ValueError(f"Entrypoint function '{factory_name}' not found in {module_import}")
        return factory()

    def _validate_skill(self, skill: Any, manifest: dict[str, Any]) -> None:
        for method_name in ("describe", "validate_config", "run"):
            if not hasattr(skill, method_name):
                raise ValueError(f"Skill is missing required method '{method_name}'")
        spec = skill.describe()
        if not isinstance(spec, SkillSpec):
            raise ValueError("describe() must return SkillSpec")
        if spec.skill_id != str(manifest["id"]):
            raise ValueError("Skill id mismatch: manifest.id != describe().skill_id")
