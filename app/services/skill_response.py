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


def _try_parse_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
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


def parse_skill_response(raw_text: str) -> SkillResponseDecision | None:
    payload = _try_parse_json_object(raw_text)
    if not payload:
        return None

    decision_type = str(payload.get("type") or "").strip()
    if decision_type == "final_answer":
        answer = payload.get("answer")
        if not isinstance(answer, dict):
            return None
        answer_text = str(answer.get("text") or "").strip()
        if not answer_text:
            return None
        return SkillResponseDecision(
            decision_type=decision_type,
            answer_text=answer_text,
            skill_call=None,
            raw_payload=payload,
        )

    if decision_type == "skill_call":
        skill_call = payload.get("skill_call")
        if not isinstance(skill_call, dict):
            return None
        skill_id = str(skill_call.get("skill_id") or "").strip()
        if not skill_id:
            return None
        arguments = skill_call.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return None
        return SkillResponseDecision(
            decision_type=decision_type,
            answer_text=None,
            skill_call=SkillCallRequest(skill_id=skill_id, arguments=arguments),
            raw_payload=payload,
        )

    return None
