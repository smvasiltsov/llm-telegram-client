from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillCallRequest:
    skill_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class SkillResponseDecision:
    decision_type: str
    answer_text: str | None
    skill_call: SkillCallRequest | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class SkillResponseParseError:
    code: str
    message: str
    detected_type: str | None = None
    hint: str | None = None
    raw_excerpt: str | None = None


def _try_parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    if text.startswith("{"):
        decoder = json.JSONDecoder()
        try:
            parsed, end = decoder.raw_decode(text, 0)
        except Exception:
            return None
        if isinstance(parsed, dict) and not text[end:].strip():
            return parsed
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            parsed, _end = decoder.raw_decode(text, idx)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _raw_excerpt(raw_text: str, limit: int = 500) -> str:
    text = str(raw_text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _looks_like_skill_response_intent(text: str) -> bool:
    lowered = text.lower()
    return '"type"' in lowered and ("skill_call" in lowered or "final_answer" in lowered)


def parse_skill_response_with_error(raw_text: str) -> tuple[SkillResponseDecision | None, SkillResponseParseError | None]:
    payload = _try_parse_json_object(raw_text)
    if not payload:
        if _looks_like_skill_response_intent(str(raw_text or "").strip()):
            return None, SkillResponseParseError(
                code="malformed_json",
                message="Assistant returned invalid JSON for skill response.",
                hint=(
                    "Return exactly one valid JSON object with balanced braces. "
                    "Use type=skill_call or type=final_answer and valid object fields."
                ),
                raw_excerpt=_raw_excerpt(raw_text),
            )
        return None, None

    decision_type = str(payload.get("type") or "").strip()
    if decision_type == "final_answer":
        answer = payload.get("answer")
        if not isinstance(answer, dict):
            return None, SkillResponseParseError(
                code="invalid_final_answer",
                message="Field 'answer' must be an object for final_answer.",
                detected_type=decision_type,
                hint='Expected: {"type":"final_answer","answer":{"text":"..."}}',
                raw_excerpt=_raw_excerpt(raw_text),
            )
        answer_text = str(answer.get("text") or "").strip()
        if not answer_text:
            return None, SkillResponseParseError(
                code="missing_answer_text",
                message="Field 'answer.text' must be a non-empty string for final_answer.",
                detected_type=decision_type,
                hint='Expected: {"type":"final_answer","answer":{"text":"..."}}',
                raw_excerpt=_raw_excerpt(raw_text),
            )
        return SkillResponseDecision(
            decision_type=decision_type,
            answer_text=answer_text,
            skill_call=None,
            raw_payload=payload,
        ), None

    if decision_type == "skill_call":
        skill_call = payload.get("skill_call")
        if not isinstance(skill_call, dict):
            return None, SkillResponseParseError(
                code="missing_skill_call",
                message="Field 'skill_call' must be an object for skill_call responses.",
                detected_type=decision_type,
                hint='Expected: {"type":"skill_call","skill_call":{"skill_id":"...","arguments":{}}}',
                raw_excerpt=_raw_excerpt(raw_text),
            )
        skill_id = str(skill_call.get("skill_id") or "").strip()
        if not skill_id:
            return None, SkillResponseParseError(
                code="missing_skill_id",
                message="Field 'skill_call.skill_id' must be a non-empty string.",
                detected_type=decision_type,
                hint='Expected: {"type":"skill_call","skill_call":{"skill_id":"...","arguments":{}}}',
                raw_excerpt=_raw_excerpt(raw_text),
            )
        arguments = skill_call.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return None, SkillResponseParseError(
                code="invalid_arguments",
                message="Field 'skill_call.arguments' must be a JSON object.",
                detected_type=decision_type,
                hint='Expected: {"type":"skill_call","skill_call":{"skill_id":"...","arguments":{}}}',
                raw_excerpt=_raw_excerpt(raw_text),
            )
        return SkillResponseDecision(
            decision_type=decision_type,
            answer_text=None,
            skill_call=SkillCallRequest(skill_id=skill_id, arguments=arguments),
            raw_payload=payload,
        ), None

    if _looks_like_skill_response_intent(str(raw_text or "").strip()):
        return None, SkillResponseParseError(
            code="unknown_type",
            message="Field 'type' must be either 'skill_call' or 'final_answer'.",
            detected_type=decision_type or None,
            hint=(
                'Use {"type":"skill_call","skill_call":{...}} for tool/skill execution '
                'or {"type":"final_answer","answer":{"text":"..."}} for a final reply.'
            ),
            raw_excerpt=_raw_excerpt(raw_text),
        )
    return None, None


def parse_skill_response(raw_text: str) -> SkillResponseDecision | None:
    parsed, _error = parse_skill_response_with_error(raw_text)
    return parsed
