from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from prepost_processing_sdk.contract import PrePostProcessingProtocol, PrePostProcessingSpec


logger = logging.getLogger("prepost_processing_registry")


@dataclass(frozen=True)
class PrePostProcessingRecord:
    manifest: dict[str, Any]
    instance: PrePostProcessingProtocol
    spec: PrePostProcessingSpec


class PrePostProcessingRegistry:
    def __init__(self) -> None:
        self._records: dict[str, PrePostProcessingRecord] = {}

    def list_specs(self) -> list[PrePostProcessingSpec]:
        return [record.spec for record in self._records.values()]

    def get(self, prepost_processing_id: str) -> PrePostProcessingRecord | None:
        return self._records.get(prepost_processing_id)

    def discover(self, prepost_processing_dir: str | Path) -> None:
        base = Path(prepost_processing_dir)
        if not base.exists() or not base.is_dir():
            logger.info("pre/post processing directory not found: %s", base)
            return

        for processor_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            manifest_path = processor_dir / "processor.yaml"
            if not manifest_path.exists():
                continue
            try:
                manifest = self._load_manifest(manifest_path)
                processor = self._load_entrypoint(processor_dir, manifest["entrypoint"])
                self._validate_processor(processor, manifest)
                spec = processor.describe()
                record = PrePostProcessingRecord(
                    manifest=manifest,
                    instance=processor,
                    spec=spec,
                )
                self._records[spec.prepost_processing_id] = record
                logger.info(
                    "pre/post processing loaded id=%s version=%s path=%s",
                    spec.prepost_processing_id,
                    spec.version,
                    processor_dir,
                )
            except Exception:
                logger.exception("pre/post processing load failed path=%s", processor_dir)

    def _load_manifest(self, manifest_path: Path) -> dict[str, Any]:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Manifest must be object: {manifest_path}")
        required = ("id", "version", "entrypoint")
        missing = [k for k in required if not str(raw.get(k, "")).strip()]
        if missing:
            raise ValueError(f"Manifest missing required keys {missing}: {manifest_path}")
        return raw

    def _load_entrypoint(self, processor_dir: Path, entrypoint: str) -> PrePostProcessingProtocol:
        if ":" not in entrypoint:
            raise ValueError(f"Invalid entrypoint '{entrypoint}', expected module:function")
        module_name, factory_name = entrypoint.split(":", 1)
        module_import = f"prepost_processing.{processor_dir.name}.{module_name}"
        module = importlib.import_module(module_import)
        factory = getattr(module, factory_name, None)
        if factory is None:
            raise ValueError(f"Entrypoint function '{factory_name}' not found in {module_import}")
        return factory()

    def _validate_processor(self, processor: Any, manifest: dict[str, Any]) -> None:
        for method_name in ("describe", "validate_config", "run"):
            if not hasattr(processor, method_name):
                raise ValueError(f"Pre/post processing is missing required method '{method_name}'")
        spec = processor.describe()
        if not isinstance(spec, PrePostProcessingSpec):
            raise ValueError("describe() must return PrePostProcessingSpec")
        if spec.prepost_processing_id != str(manifest["id"]):
            raise ValueError("Pre/post processing id mismatch: manifest.id != describe().prepost_processing_id")
