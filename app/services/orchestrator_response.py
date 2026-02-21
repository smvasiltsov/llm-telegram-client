from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OrchestratorParsedResponse:
    answer_text: str
    visibility: str
    actions: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]


def _as_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
    return result


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


def parse_orchestrator_response(raw_text: str) -> OrchestratorParsedResponse | None:
    payload = _try_parse_json_object(raw_text)
    if not payload:
        return None
    answer = payload.get("answer")
    if not isinstance(answer, dict):
        return None
    answer_text = str(answer.get("text") or "").strip()
    if not answer_text:
        return None
    visibility = str(answer.get("visibility") or "group").strip() or "group"
    actions = _as_list_of_dicts(payload.get("actions"))
    tool_calls = _as_list_of_dicts(payload.get("tool_calls"))
    return OrchestratorParsedResponse(
        answer_text=answer_text,
        visibility=visibility,
        actions=actions,
        tool_calls=tool_calls,
    )
