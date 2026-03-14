from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from skills.jira.client import JiraClient, JiraClientConfig, JiraClientError, JiraHTTPError
from skills_sdk.contract import SkillContext, SkillResult, SkillSpec


SUPPORTED_OPERATIONS: tuple[str, ...] = (
    "list_jira_projects",
    "search_jira_issues",
    "get_jira_issue",
    "list_project_issues",
    "create_jira_issue",
    "update_jira_issue",
    "get_issue_transitions",
    "transition_jira_issue",
)

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_SLEEP_SEC = 3.0
DEFAULT_MAX_ITEMS = 25
DEFAULT_MAX_CONTENT_CHARS = 12000

JIRA_SKILL_DESCRIPTION = (
    "Jira skill with 8 operations selected by arguments.operation. "
    "Runtime config accepts optional config_path only; default config file is skills/jira/config.json. "
    "Config file contains url, username, token, timeout_sec, retry_attempts, retry_sleep_sec, max_items, max_content_chars. "
    "Operations and required fields: "
    "list_jira_projects(no extra required fields), "
    "search_jira_issues(jql), "
    "get_jira_issue(issue_id_or_key), "
    "list_project_issues(project_key), "
    "create_jira_issue(project_key,issue_type,summary), "
    "update_jira_issue(issue_id_or_key and at least one of summary/description), "
    "get_issue_transitions(issue_id_or_key), "
    "transition_jira_issue(issue_id_or_key,transition_id). "
    "For enhanced search operations, use arguments.next_page_token for pagination. "
    "Output is compact and bounded by configured limits."
)

JIRA_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(SUPPORTED_OPERATIONS)},
        "limit": {"type": "integer", "minimum": 1},
        "start_at": {"type": "integer", "minimum": 0},
        "next_page_token": {"type": "string", "minLength": 1},
        "jql": {"type": "string", "minLength": 1},
        "issue_id_or_key": {"type": "string", "minLength": 1},
        "project_key": {"type": "string", "minLength": 1},
        "issue_type": {"type": "string", "minLength": 1},
        "summary": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "transition_id": {"type": "string", "minLength": 1},
    },
    "required": ["operation"],
    "oneOf": [
        {
            "properties": {"operation": {"const": "list_jira_projects"}},
            "required": ["operation"],
        },
        {
            "properties": {"operation": {"const": "search_jira_issues"}},
            "required": ["operation", "jql"],
        },
        {
            "properties": {"operation": {"const": "get_jira_issue"}},
            "required": ["operation", "issue_id_or_key"],
        },
        {
            "properties": {"operation": {"const": "list_project_issues"}},
            "required": ["operation", "project_key"],
        },
        {
            "properties": {"operation": {"const": "create_jira_issue"}},
            "required": ["operation", "project_key", "issue_type", "summary"],
        },
        {
            "properties": {"operation": {"const": "update_jira_issue"}},
            "required": ["operation", "issue_id_or_key"],
            "anyOf": [{"required": ["summary"]}, {"required": ["description"]}],
        },
        {
            "properties": {"operation": {"const": "get_issue_transitions"}},
            "required": ["operation", "issue_id_or_key"],
        },
        {
            "properties": {"operation": {"const": "transition_jira_issue"}},
            "required": ["operation", "issue_id_or_key", "transition_id"],
        },
    ],
    "additionalProperties": True,
}


class JiraSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="jira",
            name="Jira",
            version="0.1.0",
            description=JIRA_SKILL_DESCRIPTION,
            input_schema=JIRA_INPUT_SCHEMA,
            mode="read_write",
            timeout_sec=DEFAULT_TIMEOUT_SEC,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]

        config_path = config.get("config_path")
        if config_path is not None and (not isinstance(config_path, str) or not config_path.strip()):
            return ["config.config_path must be a non-empty string when provided"]

        try:
            profile = self._load_skill_config(config)
        except ValueError as exc:
            return [str(exc)]

        errors: list[str] = []
        username = profile.get("username")
        if not isinstance(username, str) or not username.strip():
            errors.append("skill config username is required")

        token = profile.get("token")
        if not isinstance(token, str) or not token.strip():
            errors.append("skill config token is required")

        url = profile.get("url")
        if not isinstance(url, str) or not url.strip():
            errors.append("skill config url is required")
        elif not self._is_valid_jira_url(url.strip()):
            errors.append("skill config url must be in format https://<site>.atlassian.net")

        timeout_sec = self._parse_int(profile.get("timeout_sec"), default=DEFAULT_TIMEOUT_SEC)
        if timeout_sec < 5 or timeout_sec > 120:
            errors.append("skill config timeout_sec must be between 5 and 120")

        retry_attempts = self._parse_int(profile.get("retry_attempts"), default=DEFAULT_RETRY_ATTEMPTS)
        if retry_attempts < 1 or retry_attempts > 10:
            errors.append("skill config retry_attempts must be between 1 and 10")

        retry_sleep_sec = self._parse_float(profile.get("retry_sleep_sec"), default=DEFAULT_RETRY_SLEEP_SEC)
        if retry_sleep_sec < 0 or retry_sleep_sec > 30:
            errors.append("skill config retry_sleep_sec must be between 0 and 30")

        max_items = self._parse_int(profile.get("max_items"), default=DEFAULT_MAX_ITEMS)
        if max_items < 1 or max_items > 100:
            errors.append("skill config max_items must be between 1 and 100")

        max_content_chars = self._parse_int(profile.get("max_content_chars"), default=DEFAULT_MAX_CONTENT_CHARS)
        if max_content_chars < 500 or max_content_chars > 100000:
            errors.append("skill config max_content_chars must be between 500 and 100000")

        return errors

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        _ = ctx
        if not isinstance(arguments, dict):
            return SkillResult(ok=False, error="arguments must be an object")

        config_errors = self.validate_config(config)
        if config_errors:
            return SkillResult(ok=False, error="; ".join(config_errors))
        profile = self._load_skill_config(config)

        operation_raw = arguments.get("operation")
        if not isinstance(operation_raw, str) or not operation_raw.strip():
            return SkillResult(ok=False, error="arguments.operation is required")
        operation = operation_raw.strip()

        handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], SkillResult]] = {
            "list_jira_projects": self._list_jira_projects,
            "search_jira_issues": self._search_jira_issues,
            "get_jira_issue": self._get_jira_issue,
            "list_project_issues": self._list_project_issues,
            "create_jira_issue": self._create_jira_issue,
            "update_jira_issue": self._update_jira_issue,
            "get_issue_transitions": self._get_issue_transitions,
            "transition_jira_issue": self._transition_jira_issue,
        }
        handler = handlers.get(operation)
        if handler is None:
            return SkillResult(
                ok=False,
                error=f"arguments.operation is unsupported: {operation}",
                metadata={"supported_operations": list(SUPPORTED_OPERATIONS)},
            )

        try:
            return handler(arguments, profile)
        except JiraHTTPError as exc:
            detail = exc.response_body or str(exc)
            return SkillResult(ok=False, error=f"{operation}: http {exc.status_code}: {detail}")
        except JiraClientError as exc:
            return SkillResult(ok=False, error=f"{operation}: {exc}")
        except ValueError as exc:
            return SkillResult(ok=False, error=f"{operation}: {exc}")
        except Exception as exc:
            return SkillResult(ok=False, error=f"{operation}: unexpected error: {exc}")

    def _list_jira_projects(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        runtime = self._runtime_config(profile)
        limit = self._effective_limit(arguments, runtime)
        start_at = self._parse_start_at(arguments.get("start_at"))

        client = self._build_client(profile)
        payload = client.get_json(
            path="/rest/api/3/project/search",
            params={"maxResults": limit, "startAt": start_at},
        )
        raw_items = self._extract_items(payload, keys=("values", "results", "items"))
        items = [self._normalize_project(item) for item in raw_items[:limit]]

        total = self._parse_int(payload.get("total"), default=len(raw_items))
        max_results = self._parse_int(payload.get("maxResults"), default=limit)
        effective_total = total if total >= len(items) else len(items)

        return SkillResult(
            ok=True,
            output={
                "items": items,
                "count": len(items),
                "start_at": start_at,
                "max_results": max_results,
                "total": effective_total,
                "truncated": (start_at + len(items)) < effective_total,
            },
        )

    def _search_jira_issues(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        jql = self._required_str(arguments.get("jql"), "arguments.jql")
        runtime = self._runtime_config(profile)
        limit = self._effective_limit(arguments, runtime)
        start_at = self._parse_start_at(arguments.get("start_at"))
        next_page_token = self._optional_str(arguments.get("next_page_token"))
        if start_at > 0 and next_page_token is None:
            raise ValueError("arguments.start_at is not supported by /search/jql; use arguments.next_page_token")

        client = self._build_client(profile)
        request_body: dict[str, Any] = {
            "jql": jql,
            "maxResults": limit,
            "fields": ["summary", "status", "assignee", "priority", "updated"],
        }
        if next_page_token is not None:
            request_body["nextPageToken"] = next_page_token
        try:
            payload = client.post_json(
                path="/rest/api/3/search/jql",
                json_body=request_body,
            )
        except JiraHTTPError as exc:
            if not self._is_unbounded_jql_error(exc):
                raise
            bounded_jql = self._make_bounded_jql(jql, days=30)
            request_body["jql"] = bounded_jql
            payload = client.post_json(
                path="/rest/api/3/search/jql",
                json_body=request_body,
            )
        return SkillResult(ok=True, output=self._normalize_issue_list(payload, start_at=start_at, limit=limit))

    def _get_jira_issue(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        issue_id_or_key = self._required_str(arguments.get("issue_id_or_key"), "arguments.issue_id_or_key")
        runtime = self._runtime_config(profile)

        client = self._build_client(profile)
        payload = client.get_json(
            path=f"/rest/api/3/issue/{issue_id_or_key}",
            params={"fields": "summary,description,status,assignee,priority,reporter,updated"},
        )
        issue = self._normalize_issue(payload, max_content_chars=runtime["max_content_chars"], include_description=True)
        return SkillResult(ok=True, output={"issue": issue, "description_truncated": bool(issue.get("description_truncated", False))})

    def _list_project_issues(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        project_key = self._required_str(arguments.get("project_key"), "arguments.project_key")
        runtime = self._runtime_config(profile)
        limit = self._effective_limit(arguments, runtime)
        start_at = self._parse_start_at(arguments.get("start_at"))
        next_page_token = self._optional_str(arguments.get("next_page_token"))
        if start_at > 0 and next_page_token is None:
            raise ValueError("arguments.start_at is not supported by /search/jql; use arguments.next_page_token")

        client = self._build_client(profile)
        jql = f"project = {project_key} ORDER BY updated DESC"
        request_body: dict[str, Any] = {
            "jql": jql,
            "maxResults": limit,
            "fields": ["summary", "status", "assignee", "priority", "updated"],
        }
        if next_page_token is not None:
            request_body["nextPageToken"] = next_page_token
        payload = client.post_json(
            path="/rest/api/3/search/jql",
            json_body=request_body,
        )
        return SkillResult(ok=True, output=self._normalize_issue_list(payload, start_at=start_at, limit=limit))

    def _create_jira_issue(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        project_key = self._required_str(arguments.get("project_key"), "arguments.project_key")
        issue_type = self._required_str(arguments.get("issue_type"), "arguments.issue_type")
        summary = self._required_str(arguments.get("summary"), "arguments.summary")
        description = self._optional_str(arguments.get("description"))

        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }
        if description is not None:
            fields["description"] = self._to_adf_doc(description)

        client = self._build_client(profile)
        payload = client.post_json(path="/rest/api/3/issue", json_body={"fields": fields})

        issue_id = self._string_or_none(payload.get("id"))
        issue_key = self._string_or_none(payload.get("key"))
        return SkillResult(
            ok=True,
            output={
                "issue": {
                    "id": issue_id,
                    "key": issue_key,
                    "url": self._build_issue_url(profile, issue_key),
                }
            },
        )

    def _update_jira_issue(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        issue_id_or_key = self._required_str(arguments.get("issue_id_or_key"), "arguments.issue_id_or_key")
        summary = self._optional_str(arguments.get("summary"))
        description = self._optional_str(arguments.get("description"))
        if summary is None and description is None:
            raise ValueError("arguments.summary or arguments.description is required")

        fields: dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = self._to_adf_doc(description)

        client = self._build_client(profile)
        client.put_json(path=f"/rest/api/3/issue/{issue_id_or_key}", json_body={"fields": fields})

        return SkillResult(
            ok=True,
            output={
                "issue": {
                    "id": None,
                    "key": issue_id_or_key,
                },
                "updated": True,
            },
        )

    def _get_issue_transitions(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        issue_id_or_key = self._required_str(arguments.get("issue_id_or_key"), "arguments.issue_id_or_key")

        client = self._build_client(profile)
        payload = client.get_json(path=f"/rest/api/3/issue/{issue_id_or_key}/transitions")
        transitions_raw = self._extract_items(payload, keys=("transitions",))
        transitions = [self._normalize_transition(item) for item in transitions_raw]
        return SkillResult(ok=True, output={"transitions": transitions, "count": len(transitions)})

    def _transition_jira_issue(self, arguments: dict[str, Any], profile: dict[str, Any]) -> SkillResult:
        issue_id_or_key = self._required_str(arguments.get("issue_id_or_key"), "arguments.issue_id_or_key")
        transition_id = self._required_str(arguments.get("transition_id"), "arguments.transition_id")

        client = self._build_client(profile)
        client.post_json(
            path=f"/rest/api/3/issue/{issue_id_or_key}/transitions",
            json_body={"transition": {"id": transition_id}},
        )
        return SkillResult(
            ok=True,
            output={
                "issue_id_or_key": issue_id_or_key,
                "transition_id": transition_id,
                "transitioned": True,
            },
        )

    def _build_client(self, skill_config: dict[str, Any]) -> JiraClient:
        runtime = self._runtime_config(skill_config)
        client_config = JiraClientConfig(
            url=runtime["url"],
            timeout_sec=runtime["timeout_sec"],
            retry_attempts=runtime["retry_attempts"],
            retry_sleep_sec=runtime["retry_sleep_sec"],
        )
        return JiraClient(config=client_config, username=runtime["username"], token=runtime["token"])

    def _runtime_config(self, skill_config: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": str(skill_config.get("url", "")).strip(),
            "username": str(skill_config.get("username", "")).strip(),
            "token": str(skill_config.get("token", "")).strip(),
            "timeout_sec": self._clamp_int(skill_config.get("timeout_sec"), default=DEFAULT_TIMEOUT_SEC, minimum=5, maximum=120),
            "retry_attempts": self._clamp_int(
                skill_config.get("retry_attempts"),
                default=DEFAULT_RETRY_ATTEMPTS,
                minimum=1,
                maximum=10,
            ),
            "retry_sleep_sec": self._clamp_float(
                skill_config.get("retry_sleep_sec"),
                default=DEFAULT_RETRY_SLEEP_SEC,
                minimum=0.0,
                maximum=30.0,
            ),
            "max_items": self._clamp_int(skill_config.get("max_items"), default=DEFAULT_MAX_ITEMS, minimum=1, maximum=100),
            "max_content_chars": self._clamp_int(
                skill_config.get("max_content_chars"),
                default=DEFAULT_MAX_CONTENT_CHARS,
                minimum=500,
                maximum=100000,
            ),
        }

    def _default_config_path(self) -> Path:
        return Path(__file__).resolve().parent / "config.json"

    def _resolve_config_path(self, config: dict[str, Any]) -> Path:
        raw_path = config.get("config_path")
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path.strip()).expanduser()
        return self._default_config_path()

    def _load_skill_config(self, config: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_config_path(config)
        if not path.exists() or not path.is_file():
            raise ValueError(f"skill config file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid skill config JSON at {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"skill config must be a JSON object: {path}")
        return raw

    def _extract_items(self, payload: dict[str, Any], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _normalize_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._string_or_none(payload.get("id")),
            "key": self._string_or_none(payload.get("key")),
            "name": self._string_or_none(payload.get("name")),
            "project_type": self._string_or_none(payload.get("projectTypeKey")),
        }

    def _normalize_issue_list(self, payload: dict[str, Any], *, start_at: int, limit: int) -> dict[str, Any]:
        raw_issues = self._extract_items(payload, keys=("issues", "results", "items"))
        items = [self._normalize_issue(issue, max_content_chars=0, include_description=False) for issue in raw_issues[:limit]]

        total = self._parse_int(payload.get("total"), default=len(raw_issues))
        max_results = self._parse_int(payload.get("maxResults"), default=limit)
        start_payload = self._parse_int(payload.get("startAt"), default=start_at)
        next_page_token = self._string_or_none(payload.get("nextPageToken"))
        effective_total = total if total >= len(items) else len(items)

        return {
            "items": items,
            "count": len(items),
            "start_at": start_payload,
            "next_page_token": next_page_token,
            "max_results": max_results,
            "total": effective_total,
            "truncated": bool(next_page_token) or (start_payload + len(items)) < effective_total,
        }

    def _normalize_issue(self, payload: dict[str, Any], *, max_content_chars: int, include_description: bool) -> dict[str, Any]:
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}

        issue: dict[str, Any] = {
            "id": self._string_or_none(payload.get("id")),
            "key": self._string_or_none(payload.get("key")),
            "summary": self._string_or_none(fields.get("summary")),
            "status": self._string_or_none(self._nested_get(fields, ["status", "name"])),
            "assignee": self._string_or_none(self._nested_get(fields, ["assignee", "displayName"])),
            "priority": self._string_or_none(self._nested_get(fields, ["priority", "name"])),
            "reporter": self._string_or_none(self._nested_get(fields, ["reporter", "displayName"])),
            "updated": self._string_or_none(fields.get("updated")),
        }

        if include_description:
            text = self._extract_description_text(fields.get("description"))
            truncated = False
            if len(text) > max_content_chars:
                text = text[:max_content_chars]
                truncated = True
            issue["description"] = text
            issue["description_truncated"] = truncated

        return issue

    def _normalize_transition(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._string_or_none(payload.get("id")),
            "name": self._string_or_none(payload.get("name")),
            "to_status": self._string_or_none(self._nested_get(payload, ["to", "name"])),
        }

    def _extract_description_text(self, raw: Any) -> str:
        chunks: list[str] = []

        def _walk(node: Any) -> None:
            if isinstance(node, str):
                if node:
                    chunks.append(node)
                return
            if isinstance(node, list):
                for item in node:
                    _walk(item)
                return
            if isinstance(node, dict):
                text = node.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
                for key in ("content", "value"):
                    if key in node:
                        _walk(node.get(key))

        _walk(raw)
        return " ".join(part.strip() for part in chunks if part.strip())

    def _to_adf_doc(self, text: str) -> dict[str, Any]:
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }

    def _build_issue_url(self, profile: dict[str, Any], issue_key: str | None) -> str | None:
        if not issue_key:
            return None
        base = str(profile.get("url", "")).rstrip("/")
        if not base:
            return None
        return f"{base}/browse/{issue_key}"

    def _effective_limit(self, arguments: dict[str, Any], runtime: dict[str, Any]) -> int:
        requested = self._parse_int(arguments.get("limit"), default=runtime["max_items"])
        requested = max(1, requested)
        return min(requested, runtime["max_items"])

    def _parse_start_at(self, value: Any) -> int:
        return max(0, self._parse_int(value, default=0))

    def _required_str(self, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")
        return value.strip()

    def _optional_str(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if stripped else None

    def _parse_int(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _parse_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _clamp_int(self, value: Any, *, default: int, minimum: int, maximum: int) -> int:
        parsed = self._parse_int(value, default=default)
        return min(maximum, max(minimum, parsed))

    def _clamp_float(self, value: Any, *, default: float, minimum: float, maximum: float) -> float:
        parsed = self._parse_float(value, default=default)
        return min(maximum, max(minimum, parsed))

    def _nested_get(self, payload: dict[str, Any], path: list[str]) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _is_unbounded_jql_error(self, error: JiraHTTPError) -> bool:
        if int(error.status_code) != 400:
            return False
        body = error.response_body or ""
        return "Unbounded JQL queries are not allowed here" in body

    def _make_bounded_jql(self, jql: str, *, days: int) -> str:
        raw = jql.strip()
        if not raw:
            return f"updated >= -{days}d ORDER BY updated DESC"

        marker = " order by "
        raw_lower = raw.lower()
        idx = raw_lower.find(marker)
        if idx >= 0:
            base = raw[:idx].strip()
            order = raw[idx + 1 :].strip()
            if not base:
                base = f"updated >= -{days}d"
            else:
                base = f"({base}) AND updated >= -{days}d"
            return f"{base} {order}"
        return f"({raw}) AND updated >= -{days}d ORDER BY updated DESC"

    def _is_valid_jira_url(self, value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            return False
        if not parsed.netloc.endswith(".atlassian.net"):
            return False
        return parsed.path in ("", "/")


def create_skill() -> JiraSkill:
    return JiraSkill()
