from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._fs_common import resolve_root, validate_root_config
from skills_sdk.contract import SkillContext, SkillResult, SkillSpec


REQUIRED_FIELDS: tuple[str, ...] = (
    "request_understanding",
    "understood_elements",
    "blind_spots",
    "unknown_terms",
    "questions_for_user",
    "suggested_internal_context",
    "suggested_external_context",
    "minimum_context_needed_for_goal_framing",
    "goal_framing_readiness",
)

ENUM_CONFIDENCE = {"high", "medium", "low"}
ENUM_UNDERSTOOD_TYPE = {"objective", "desired_outcome", "constraint", "resource", "context", "assumption", "other"}
ENUM_BLIND_SPOT_CATEGORY = {
    "missing_business_context",
    "missing_technical_context",
    "missing_domain_context",
    "missing_success_criteria",
    "missing_constraints",
    "missing_existing_system_context",
    "missing_terminology_understanding",
    "missing_scope_definition",
    "missing_stakeholder_context",
    "missing_dependency_context",
    "ambiguity",
    "other",
}
ENUM_IMPACT_LEVEL = {"high", "medium", "low"}
ENUM_BLOCKING_LEVEL = {"blocking", "important", "helpful"}
ENUM_RESOLUTION_SOURCE = {"user", "internet", "confluence", "jira", "git", "sql", "internal_unknown"}
ENUM_INTERNAL_SOURCE = {"confluence", "jira", "git", "sql", "internal_unknown"}
ENUM_EXTERNAL_SOURCE = {"internet"}
ENUM_PRIORITY = {"high", "medium", "low"}
ENUM_READINESS = {"ready", "partially_ready", "not_ready"}

REQUIRED_FILENAMES: tuple[str, ...] = (
    "00_request_understanding.md",
    "01_understood_elements.md",
    "02_blind_spots.md",
    "03_unknown_terms.md",
    "04_questions_for_user.md",
    "05_internal_context_requests.md",
    "06_external_context_requests.md",
    "07_minimum_context_for_goal_framing.md",
    "08_goal_framing_readiness.md",
    "raw_payload.json",
)
OPTIONAL_FILENAMES: tuple[str, ...] = ("index.md",)


class FSSaveBlindSpotArtifactsSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="fs_save_blind_spot_artifacts",
            name="FS Save Blind Spot Artifacts",
            version="0.1.0",
            description=(
                "Accepts BlindSpotDetector payload as arguments (no wrapper fields), validates schema/enums/references, "
                "uses required config.root_dir, writes deterministic "
                "markdown artifacts and raw_payload.json into root_dir/working_memory/<context>, and replaces prior artifacts."
            ),
            input_schema={
                "type": "object",
                "required": list(REQUIRED_FIELDS),
                "additionalProperties": False,
                "properties": {
                    "request_understanding": {
                        "type": "object",
                        "required": ["summary", "confidence"],
                        "additionalProperties": False,
                        "properties": {
                            "summary": {"type": "string", "minLength": 1},
                            "confidence": {"type": "string", "enum": sorted(ENUM_CONFIDENCE)},
                        },
                    },
                    "understood_elements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "value", "confidence", "evidence"],
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": sorted(ENUM_UNDERSTOOD_TYPE)},
                                "value": {"type": "string", "minLength": 1},
                                "confidence": {"type": "string", "enum": sorted(ENUM_CONFIDENCE)},
                                "evidence": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "blind_spots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "id",
                                "category",
                                "title",
                                "description",
                                "why_it_matters",
                                "impact_level",
                                "blocking_level",
                                "resolution_source",
                            ],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "category": {"type": "string", "enum": sorted(ENUM_BLIND_SPOT_CATEGORY)},
                                "title": {"type": "string", "minLength": 1},
                                "description": {"type": "string", "minLength": 1},
                                "why_it_matters": {"type": "string", "minLength": 1},
                                "impact_level": {"type": "string", "enum": sorted(ENUM_IMPACT_LEVEL)},
                                "blocking_level": {"type": "string", "enum": sorted(ENUM_BLOCKING_LEVEL)},
                                "resolution_source": {"type": "string", "enum": sorted(ENUM_RESOLUTION_SOURCE)},
                            },
                        },
                    },
                    "unknown_terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["term", "why_unclear", "possible_meanings", "resolution_source", "priority"],
                            "additionalProperties": False,
                            "properties": {
                                "term": {"type": "string", "minLength": 1},
                                "why_unclear": {"type": "string", "minLength": 1},
                                "possible_meanings": {"type": "array", "items": {"type": "string", "minLength": 1}},
                                "resolution_source": {"type": "string", "enum": sorted(ENUM_RESOLUTION_SOURCE)},
                                "priority": {"type": "string", "enum": sorted(ENUM_PRIORITY)},
                            },
                        },
                    },
                    "questions_for_user": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "question", "why_this_question", "linked_blind_spot_ids", "priority"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "question": {"type": "string", "minLength": 1},
                                "why_this_question": {"type": "string", "minLength": 1},
                                "linked_blind_spot_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
                                "priority": {"type": "string", "enum": sorted(ENUM_PRIORITY)},
                            },
                        },
                    },
                    "suggested_internal_context": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "source", "query_intent", "why_needed", "linked_blind_spot_ids", "priority"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "source": {"type": "string", "enum": sorted(ENUM_INTERNAL_SOURCE)},
                                "query_intent": {"type": "string", "minLength": 1},
                                "why_needed": {"type": "string", "minLength": 1},
                                "linked_blind_spot_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
                                "priority": {"type": "string", "enum": sorted(ENUM_PRIORITY)},
                            },
                        },
                    },
                    "suggested_external_context": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "source", "query_intent", "why_needed", "linked_blind_spot_ids", "priority"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string", "minLength": 1},
                                "source": {"type": "string", "enum": sorted(ENUM_EXTERNAL_SOURCE)},
                                "query_intent": {"type": "string", "minLength": 1},
                                "why_needed": {"type": "string", "minLength": 1},
                                "linked_blind_spot_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
                                "priority": {"type": "string", "enum": sorted(ENUM_PRIORITY)},
                            },
                        },
                    },
                    "minimum_context_needed_for_goal_framing": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["item", "why_required", "source", "priority"],
                            "additionalProperties": False,
                            "properties": {
                                "item": {"type": "string", "minLength": 1},
                                "why_required": {"type": "string", "minLength": 1},
                                "source": {"type": "string", "enum": sorted(ENUM_RESOLUTION_SOURCE)},
                                "priority": {"type": "string", "enum": sorted(ENUM_PRIORITY)},
                            },
                        },
                    },
                    "goal_framing_readiness": {
                        "type": "object",
                        "required": ["status", "reason"],
                        "additionalProperties": False,
                        "properties": {
                            "status": {"type": "string", "enum": sorted(ENUM_READINESS)},
                            "reason": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
            mode="write_only",
            timeout_sec=20,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        return validate_root_config(config)

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        if not isinstance(arguments, dict):
            return self._error("VALIDATION_ERROR", "input payload must be a JSON object", field="payload")

        try:
            self._validate_payload(arguments)
        except ValueError as exc:
            field_name = getattr(exc, "field_name", None)
            return self._error("VALIDATION_ERROR", str(exc), field=field_name)

        try:
            base_dir = self._resolve_working_memory_dir(ctx, resolve_root(config))
        except ValueError as exc:
            return self._error("MEMORY_PATH_RESOLUTION_ERROR", str(exc))
        except Exception:
            return self._error("MEMORY_PATH_RESOLUTION_ERROR", "config.root_dir is required")

        try:
            files = self._write_artifacts(base_dir, arguments)
        except ValueError as exc:
            return self._error("FILE_WRITE_ERROR", str(exc))
        except OSError as exc:
            return self._error("FILE_WRITE_ERROR", str(exc))
        except Exception as exc:
            return self._error("INTERNAL_ERROR", str(exc))

        return SkillResult(
            ok=True,
            output={
                "status": "ok",
                "base_dir": str(base_dir),
                "files_written": files,
                "warnings": [],
            },
        )

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        keys = set(payload.keys())
        expected = set(REQUIRED_FIELDS)
        missing = [item for item in REQUIRED_FIELDS if item not in payload]
        if missing:
            raise self._validation_error(f"missing required top-level field: {missing[0]}", field=missing[0])
        extra = sorted(keys - expected)
        if extra:
            raise self._validation_error(f"unexpected top-level field: {extra[0]}", field=extra[0])

        self._validate_request_understanding(payload["request_understanding"])
        self._validate_understood_elements(payload["understood_elements"])
        blind_ids = self._validate_blind_spots(payload["blind_spots"])
        self._validate_unknown_terms(payload["unknown_terms"])
        self._validate_questions_for_user(payload["questions_for_user"], blind_ids=blind_ids)
        self._validate_internal_context(payload["suggested_internal_context"], blind_ids=blind_ids)
        self._validate_external_context(payload["suggested_external_context"], blind_ids=blind_ids)
        self._validate_minimum_context(payload["minimum_context_needed_for_goal_framing"])
        self._validate_goal_framing(payload["goal_framing_readiness"])

    def _validate_request_understanding(self, value: Any) -> None:
        obj = self._require_object(value, "request_understanding")
        self._require_no_extra_fields(obj, {"summary", "confidence"}, "request_understanding")
        self._require_string(obj.get("summary"), "request_understanding.summary")
        self._require_enum(obj.get("confidence"), "request_understanding.confidence", ENUM_CONFIDENCE)

    def _validate_understood_elements(self, value: Any) -> None:
        items = self._require_array(value, "understood_elements")
        for idx, item in enumerate(items):
            base = f"understood_elements[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"type", "value", "confidence", "evidence"}, base)
            self._require_enum(obj.get("type"), f"{base}.type", ENUM_UNDERSTOOD_TYPE)
            self._require_string(obj.get("value"), f"{base}.value")
            self._require_enum(obj.get("confidence"), f"{base}.confidence", ENUM_CONFIDENCE)
            self._require_string(obj.get("evidence"), f"{base}.evidence")

    def _validate_blind_spots(self, value: Any) -> set[str]:
        items = self._require_array(value, "blind_spots")
        ids: set[str] = set()
        for idx, item in enumerate(items):
            base = f"blind_spots[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(
                obj,
                {"id", "category", "title", "description", "why_it_matters", "impact_level", "blocking_level", "resolution_source"},
                base,
            )
            blind_id = self._require_string(obj.get("id"), f"{base}.id")
            if blind_id in ids:
                raise self._validation_error(f"duplicate blind_spots.id: {blind_id}", field=f"{base}.id")
            ids.add(blind_id)
            self._require_enum(obj.get("category"), f"{base}.category", ENUM_BLIND_SPOT_CATEGORY)
            self._require_string(obj.get("title"), f"{base}.title")
            self._require_string(obj.get("description"), f"{base}.description")
            self._require_string(obj.get("why_it_matters"), f"{base}.why_it_matters")
            self._require_enum(obj.get("impact_level"), f"{base}.impact_level", ENUM_IMPACT_LEVEL)
            self._require_enum(obj.get("blocking_level"), f"{base}.blocking_level", ENUM_BLOCKING_LEVEL)
            self._require_enum(obj.get("resolution_source"), f"{base}.resolution_source", ENUM_RESOLUTION_SOURCE)
        return ids

    def _validate_unknown_terms(self, value: Any) -> None:
        items = self._require_array(value, "unknown_terms")
        for idx, item in enumerate(items):
            base = f"unknown_terms[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"term", "why_unclear", "possible_meanings", "resolution_source", "priority"}, base)
            self._require_string(obj.get("term"), f"{base}.term")
            self._require_string(obj.get("why_unclear"), f"{base}.why_unclear")
            meanings = self._require_array(obj.get("possible_meanings"), f"{base}.possible_meanings")
            for mean_idx, meaning in enumerate(meanings):
                self._require_string(meaning, f"{base}.possible_meanings[{mean_idx}]")
            self._require_enum(obj.get("resolution_source"), f"{base}.resolution_source", ENUM_RESOLUTION_SOURCE)
            self._require_enum(obj.get("priority"), f"{base}.priority", ENUM_PRIORITY)

    def _validate_questions_for_user(self, value: Any, *, blind_ids: set[str]) -> None:
        items = self._require_array(value, "questions_for_user")
        for idx, item in enumerate(items):
            base = f"questions_for_user[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"id", "question", "why_this_question", "linked_blind_spot_ids", "priority"}, base)
            self._require_string(obj.get("id"), f"{base}.id")
            self._require_string(obj.get("question"), f"{base}.question")
            self._require_string(obj.get("why_this_question"), f"{base}.why_this_question")
            linked = self._require_array(obj.get("linked_blind_spot_ids"), f"{base}.linked_blind_spot_ids")
            self._validate_linked_blind_ids(linked, blind_ids=blind_ids, field=f"{base}.linked_blind_spot_ids")
            self._require_enum(obj.get("priority"), f"{base}.priority", ENUM_PRIORITY)

    def _validate_internal_context(self, value: Any, *, blind_ids: set[str]) -> None:
        items = self._require_array(value, "suggested_internal_context")
        for idx, item in enumerate(items):
            base = f"suggested_internal_context[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"id", "source", "query_intent", "why_needed", "linked_blind_spot_ids", "priority"}, base)
            self._require_string(obj.get("id"), f"{base}.id")
            self._require_enum(obj.get("source"), f"{base}.source", ENUM_INTERNAL_SOURCE)
            self._require_string(obj.get("query_intent"), f"{base}.query_intent")
            self._require_string(obj.get("why_needed"), f"{base}.why_needed")
            linked = self._require_array(obj.get("linked_blind_spot_ids"), f"{base}.linked_blind_spot_ids")
            self._validate_linked_blind_ids(linked, blind_ids=blind_ids, field=f"{base}.linked_blind_spot_ids")
            self._require_enum(obj.get("priority"), f"{base}.priority", ENUM_PRIORITY)

    def _validate_external_context(self, value: Any, *, blind_ids: set[str]) -> None:
        items = self._require_array(value, "suggested_external_context")
        for idx, item in enumerate(items):
            base = f"suggested_external_context[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"id", "source", "query_intent", "why_needed", "linked_blind_spot_ids", "priority"}, base)
            self._require_string(obj.get("id"), f"{base}.id")
            self._require_enum(obj.get("source"), f"{base}.source", ENUM_EXTERNAL_SOURCE)
            self._require_string(obj.get("query_intent"), f"{base}.query_intent")
            self._require_string(obj.get("why_needed"), f"{base}.why_needed")
            linked = self._require_array(obj.get("linked_blind_spot_ids"), f"{base}.linked_blind_spot_ids")
            self._validate_linked_blind_ids(linked, blind_ids=blind_ids, field=f"{base}.linked_blind_spot_ids")
            self._require_enum(obj.get("priority"), f"{base}.priority", ENUM_PRIORITY)

    def _validate_minimum_context(self, value: Any) -> None:
        items = self._require_array(value, "minimum_context_needed_for_goal_framing")
        for idx, item in enumerate(items):
            base = f"minimum_context_needed_for_goal_framing[{idx}]"
            obj = self._require_object(item, base)
            self._require_no_extra_fields(obj, {"item", "why_required", "source", "priority"}, base)
            self._require_string(obj.get("item"), f"{base}.item")
            self._require_string(obj.get("why_required"), f"{base}.why_required")
            self._require_enum(obj.get("source"), f"{base}.source", ENUM_RESOLUTION_SOURCE)
            self._require_enum(obj.get("priority"), f"{base}.priority", ENUM_PRIORITY)

    def _validate_goal_framing(self, value: Any) -> None:
        obj = self._require_object(value, "goal_framing_readiness")
        self._require_no_extra_fields(obj, {"status", "reason"}, "goal_framing_readiness")
        self._require_enum(obj.get("status"), "goal_framing_readiness.status", ENUM_READINESS)
        self._require_string(obj.get("reason"), "goal_framing_readiness.reason")

    def _validate_linked_blind_ids(self, linked_values: list[Any], *, blind_ids: set[str], field: str) -> None:
        for idx, raw in enumerate(linked_values):
            linked_id = self._require_string(raw, f"{field}[{idx}]")
            if linked_id not in blind_ids:
                raise self._validation_error(
                    f"linked_blind_spot_ids contains unknown ID: {linked_id}",
                    field=f"{field}[{idx}]",
                )

    def _resolve_working_memory_dir(self, ctx: SkillContext, root_path: Path) -> Path:
        base_parent = (root_path / "working_memory").resolve()
        self._ensure_relative_to(base_parent, root_path, "working-memory parent escapes root_dir")
        base_parent.mkdir(parents=True, exist_ok=True)

        context_dir_name = self._context_dir_name(ctx)
        base_dir = (base_parent / context_dir_name).resolve()
        self._ensure_relative_to(base_dir, base_parent, "resolved working-memory directory escapes parent")
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def _context_dir_name(self, ctx: SkillContext) -> str:
        return f"chat_{ctx.chat_id}_user_{ctx.user_id}_role_{ctx.role_id}"

    def _write_artifacts(self, base_dir: Path, payload: dict[str, Any]) -> list[str]:
        self._remove_managed_files(base_dir)

        mapping: dict[str, str] = {
            "00_request_understanding.md": self._render_request_understanding(payload["request_understanding"]),
            "01_understood_elements.md": self._render_understood_elements(payload["understood_elements"]),
            "02_blind_spots.md": self._render_blind_spots(payload["blind_spots"]),
            "03_unknown_terms.md": self._render_unknown_terms(payload["unknown_terms"]),
            "04_questions_for_user.md": self._render_questions(payload["questions_for_user"]),
            "05_internal_context_requests.md": self._render_internal_context(payload["suggested_internal_context"]),
            "06_external_context_requests.md": self._render_external_context(payload["suggested_external_context"]),
            "07_minimum_context_for_goal_framing.md": self._render_minimum_context(payload["minimum_context_needed_for_goal_framing"]),
            "08_goal_framing_readiness.md": self._render_goal_framing(payload["goal_framing_readiness"]),
            "raw_payload.json": json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        }

        written: list[str] = []
        for filename in REQUIRED_FILENAMES:
            target = self._safe_child(base_dir, filename)
            target.write_text(mapping[filename], encoding="utf-8")
            written.append(str(target))
        return written

    def _remove_managed_files(self, base_dir: Path) -> None:
        for filename in REQUIRED_FILENAMES + OPTIONAL_FILENAMES:
            target = self._safe_child(base_dir, filename)
            if target.exists() and target.is_file():
                target.unlink()

    def _safe_child(self, base: Path, filename: str) -> Path:
        target = (base / filename).resolve()
        self._ensure_relative_to(target, base, f"unsafe target path: {filename}")
        return target

    def _render_request_understanding(self, obj: dict[str, Any]) -> str:
        return (
            "# Request Understanding\n\n"
            "## Summary\n"
            f"{obj['summary']}\n\n"
            "## Confidence\n"
            f"{obj['confidence']}\n"
        )

    def _render_understood_elements(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Understood Elements", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for idx, item in enumerate(items, start=1):
            lines.extend(
                [
                    f"## Item {idx}",
                    f"- Type: {item['type']}",
                    f"- Value: {item['value']}",
                    f"- Confidence: {item['confidence']}",
                    f"- Evidence: {item['evidence']}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _render_blind_spots(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Blind Spots", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for item in items:
            lines.extend(
                [
                    f"## {item['id']} — {item['title']}",
                    f"- Category: {item['category']}",
                    f"- Description: {item['description']}",
                    f"- Why It Matters: {item['why_it_matters']}",
                    f"- Impact Level: {item['impact_level']}",
                    f"- Blocking Level: {item['blocking_level']}",
                    f"- Resolution Source: {item['resolution_source']}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _render_unknown_terms(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Unknown Terms", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for idx, item in enumerate(items, start=1):
            lines.extend(
                [
                    f"## Term {idx}: {item['term']}",
                    f"- Why Unclear: {item['why_unclear']}",
                    "- Possible Meanings:",
                ]
            )
            if item["possible_meanings"]:
                for meaning in item["possible_meanings"]:
                    lines.append(f"  - {meaning}")
            else:
                lines.append("  - No items.")
            lines.extend(
                [
                    f"- Resolution Source: {item['resolution_source']}",
                    f"- Priority: {item['priority']}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _render_questions(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Questions for User", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for item in items:
            lines.extend(
                [
                    f"## {item['id']}",
                    f"- Question: {item['question']}",
                    f"- Why This Question: {item['why_this_question']}",
                    "- Linked Blind Spots:",
                ]
            )
            if item["linked_blind_spot_ids"]:
                for linked in item["linked_blind_spot_ids"]:
                    lines.append(f"  - {linked}")
            else:
                lines.append("  - No items.")
            lines.extend([f"- Priority: {item['priority']}", ""])
        return "\n".join(lines)

    def _render_internal_context(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Suggested Internal Context", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for item in items:
            lines.extend(
                [
                    f"## {item['id']}",
                    f"- Source: {item['source']}",
                    f"- Query Intent: {item['query_intent']}",
                    f"- Why Needed: {item['why_needed']}",
                    "- Linked Blind Spots:",
                ]
            )
            if item["linked_blind_spot_ids"]:
                for linked in item["linked_blind_spot_ids"]:
                    lines.append(f"  - {linked}")
            else:
                lines.append("  - No items.")
            lines.extend([f"- Priority: {item['priority']}", ""])
        return "\n".join(lines)

    def _render_external_context(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Suggested External Context", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for item in items:
            lines.extend(
                [
                    f"## {item['id']}",
                    f"- Source: {item['source']}",
                    f"- Query Intent: {item['query_intent']}",
                    f"- Why Needed: {item['why_needed']}",
                    "- Linked Blind Spots:",
                ]
            )
            if item["linked_blind_spot_ids"]:
                for linked in item["linked_blind_spot_ids"]:
                    lines.append(f"  - {linked}")
            else:
                lines.append("  - No items.")
            lines.extend([f"- Priority: {item['priority']}", ""])
        return "\n".join(lines)

    def _render_minimum_context(self, items: list[dict[str, Any]]) -> str:
        lines = ["# Minimum Context Needed for Goal Framing", ""]
        if not items:
            lines.extend(["No items.", ""])
            return "\n".join(lines)
        for idx, item in enumerate(items, start=1):
            lines.extend(
                [
                    f"## Item {idx}",
                    f"- Item: {item['item']}",
                    f"- Why Required: {item['why_required']}",
                    f"- Source: {item['source']}",
                    f"- Priority: {item['priority']}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _render_goal_framing(self, obj: dict[str, Any]) -> str:
        return (
            "# Goal Framing Readiness\n\n"
            f"- Status: {obj['status']}\n"
            f"- Reason: {obj['reason']}\n"
        )

    def _require_object(self, value: Any, field: str) -> dict[str, Any]:
        if value is None:
            raise self._validation_error(f"{field} must not be null", field=field)
        if not isinstance(value, dict):
            raise self._validation_error(f"{field} must be an object", field=field)
        return value

    def _require_array(self, value: Any, field: str) -> list[Any]:
        if value is None:
            raise self._validation_error(f"{field} must not be null", field=field)
        if not isinstance(value, list):
            raise self._validation_error(f"{field} must be an array", field=field)
        return value

    def _require_string(self, value: Any, field: str) -> str:
        if value is None:
            raise self._validation_error(f"{field} must not be null", field=field)
        if not isinstance(value, str) or not value.strip():
            raise self._validation_error(f"{field} must be a non-empty string", field=field)
        return value.strip()

    def _require_enum(self, value: Any, field: str, allowed: set[str]) -> str:
        normalized = self._require_string(value, field)
        if normalized not in allowed:
            raise self._validation_error(f"{field} has invalid enum value: {normalized}", field=field)
        return normalized

    def _require_no_extra_fields(self, obj: dict[str, Any], required: set[str], field: str) -> None:
        missing = [name for name in required if name not in obj]
        if missing:
            raise self._validation_error(f"missing required field: {field}.{missing[0]}", field=f"{field}.{missing[0]}")
        extra = sorted(set(obj.keys()) - required)
        if extra:
            raise self._validation_error(f"unexpected field: {field}.{extra[0]}", field=f"{field}.{extra[0]}")

    def _ensure_relative_to(self, child: Path, parent: Path, message: str) -> None:
        try:
            child.relative_to(parent)
        except ValueError as exc:
            raise ValueError(message) from exc

    def _error(self, code: str, message: str, *, field: str | None = None) -> SkillResult:
        details: dict[str, Any] = {}
        if field is not None:
            details["field"] = field
        return SkillResult(
            ok=False,
            error=message,
            output={
                "status": "error",
                "error_code": code,
                "message": message,
                "details": details,
            },
        )

    def _validation_error(self, message: str, *, field: str) -> ValueError:
        error = ValueError(message)
        setattr(error, "field_name", field)
        return error


def create_skill() -> FSSaveBlindSpotArtifactsSkill:
    return FSSaveBlindSpotArtifactsSkill()
