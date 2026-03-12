from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from skills.confluence.client import (
    ConfluenceClient,
    ConfluenceClientConfig,
    ConfluenceClientError,
    ConfluenceHTTPError,
)
from skills_sdk.contract import SkillContext, SkillResult, SkillSpec


SUPPORTED_OPERATIONS: tuple[str, ...] = (
    "search_confluence",
    "get_confluence_page",
    "batch_get_pages",
    "list_confluence_spaces",
    "list_confluence_pages",
    "get_page_tree",
    "create_confluence_page",
    "update_confluence_page",
    "append_confluence_page",
)

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_SLEEP_SEC = 3.0
DEFAULT_MAX_ITEMS = 25
DEFAULT_MAX_CONTENT_CHARS = 12000
DEFAULT_MAX_TREE_NODES = 200
DEFAULT_CONFIG_FILENAME = "config.json"
CONFLUENCE_SKILL_DESCRIPTION = (
    "Confluence skill with 9 operations selected by arguments.operation. "
    "Config source: runtime config supports only optional config_path; if omitted, "
    "the skill reads skills/confluence/config.json. "
    "Config file requirements: url, username, token, timeout_sec, retry_attempts, "
    "retry_sleep_sec, max_items, max_content_chars, max_tree_nodes. "
    "Search uses CQL via /rest/api/search. Page and space operations use /api/v2/* endpoints. "
    "Write body format is storage only. "
    "Per operation required fields: "
    "search_confluence(query); "
    "get_confluence_page(page_id); "
    "batch_get_pages(page_ids); "
    "list_confluence_spaces(no additional required fields); "
    "list_confluence_pages(space_id); "
    "get_page_tree(root_page_id); "
    "create_confluence_page(space_id,title,body_storage); "
    "update_confluence_page(page_id and at least one of title/body_storage); "
    "append_confluence_page(page_id,append_storage). "
    "Bounded output rules: limit is capped by max_items, body text by max_content_chars, "
    "tree traversal by max_tree_nodes. "
    "Version conflict 409 for update/append is returned as an error without retry."
)
CONFLUENCE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(SUPPORTED_OPERATIONS)},
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1},
        "cursor": {"type": "string"},
        "page_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "include_body": {"type": "boolean"},
        "page_ids": {
            "type": "array",
            "items": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
            "minItems": 1,
            "maxItems": 50,
        },
        "keys": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "space_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "parent_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "status": {"type": "string", "minLength": 1},
        "root_page_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": 20},
        "include_root": {"type": "boolean"},
        "title": {"type": "string", "minLength": 1},
        "body_storage": {"type": "string", "minLength": 1},
        "version": {"type": "integer", "minimum": 1},
        "append_storage": {"type": "string", "minLength": 1},
        "separator": {"type": "string"},
    },
    "required": ["operation"],
    "oneOf": [
        {
            "properties": {"operation": {"const": "search_confluence"}},
            "required": ["operation", "query"],
        },
        {
            "properties": {"operation": {"const": "get_confluence_page"}},
            "required": ["operation", "page_id"],
        },
        {
            "properties": {"operation": {"const": "batch_get_pages"}},
            "required": ["operation", "page_ids"],
        },
        {
            "properties": {"operation": {"const": "list_confluence_spaces"}},
            "required": ["operation"],
        },
        {
            "properties": {"operation": {"const": "list_confluence_pages"}},
            "required": ["operation", "space_id"],
        },
        {
            "properties": {"operation": {"const": "get_page_tree"}},
            "required": ["operation", "root_page_id"],
        },
        {
            "properties": {"operation": {"const": "create_confluence_page"}},
            "required": ["operation", "space_id", "title", "body_storage"],
        },
        {
            "properties": {"operation": {"const": "update_confluence_page"}},
            "required": ["operation", "page_id"],
            "anyOf": [{"required": ["title"]}, {"required": ["body_storage"]}],
        },
        {
            "properties": {"operation": {"const": "append_confluence_page"}},
            "required": ["operation", "page_id", "append_storage"],
        },
    ],
    "additionalProperties": True,
}


class ConfluenceSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="confluence",
            name="Confluence",
            version="0.1.0",
            description=CONFLUENCE_SKILL_DESCRIPTION,
            input_schema=CONFLUENCE_INPUT_SCHEMA,
            mode="read_write",
            timeout_sec=DEFAULT_TIMEOUT_SEC,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]

        errors: list[str] = []
        try:
            profile = self._load_skill_config(config)
        except ValueError as exc:
            return [str(exc)]

        username = profile.get("username")
        if not isinstance(username, str) or not username.strip():
            errors.append("skill config username is required")

        token = profile.get("token")
        if not isinstance(token, str) or not token.strip():
            errors.append("skill config token is required")

        url = profile.get("url")
        if not isinstance(url, str) or not url.strip():
            errors.append("skill config url is required")
        elif not self._is_valid_confluence_url(url.strip()):
            errors.append("skill config url must be in format https://<site>.atlassian.net/wiki")

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

        max_tree_nodes = self._parse_int(profile.get("max_tree_nodes"), default=DEFAULT_MAX_TREE_NODES)
        if max_tree_nodes < 1 or max_tree_nodes > 1000:
            errors.append("skill config max_tree_nodes must be between 1 and 1000")

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
            "search_confluence": self._search_confluence,
            "get_confluence_page": self._get_confluence_page,
            "batch_get_pages": self._batch_get_pages,
            "list_confluence_spaces": self._list_confluence_spaces,
            "list_confluence_pages": self._list_confluence_pages,
            "get_page_tree": self._get_page_tree,
            "create_confluence_page": self._create_confluence_page,
            "update_confluence_page": self._update_confluence_page,
            "append_confluence_page": self._append_confluence_page,
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
        except ConfluenceHTTPError as exc:
            detail = exc.response_body or str(exc)
            if exc.status_code == 409:
                return SkillResult(ok=False, error=f"{operation}: version conflict (409): {detail}")
            return SkillResult(ok=False, error=f"{operation}: http {exc.status_code}: {detail}")
        except ConfluenceClientError as exc:
            return SkillResult(ok=False, error=f"{operation}: {exc}")
        except ValueError as exc:
            return SkillResult(ok=False, error=f"{operation}: {exc}")
        except Exception as exc:
            return SkillResult(ok=False, error=f"{operation}: unexpected error: {exc}")

    def _search_confluence(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        query = self._required_str(arguments.get("query"), "arguments.query")
        runtime = self._runtime_config(config)
        limit = self._effective_limit(arguments, runtime)
        cursor = self._optional_str(arguments.get("cursor"))

        client = self._build_client(config)
        params: dict[str, Any] = {"cql": query, "limit": limit}
        if cursor:
            params["cursor"] = cursor

        # Confluence Cloud currently exposes CQL search via the v1 search resource.
        payload = client.get_json(path="/rest/api/search", params=params)
        raw_items = self._extract_items(payload)
        normalized = [self._normalize_search_hit(item) for item in raw_items[:limit]]

        return SkillResult(
            ok=True,
            output={
                "items": normalized,
                "count": len(normalized),
                "next_cursor": self._extract_next_cursor(payload),
                "truncated": len(raw_items) > len(normalized),
            },
        )

    def _get_confluence_page(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        page_id = self._required_id(arguments.get("page_id"), "arguments.page_id")
        include_body = self._parse_bool(arguments.get("include_body"), default=True)
        runtime = self._runtime_config(config)

        page = self._fetch_page(page_id=page_id, include_body=include_body, config=config)
        normalized = self._normalize_page(page, include_body=include_body, max_content_chars=runtime["max_content_chars"])
        return SkillResult(ok=True, output={"page": normalized})

    def _batch_get_pages(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        ids_raw = arguments.get("page_ids")
        if not isinstance(ids_raw, list) or not ids_raw:
            raise ValueError("arguments.page_ids must be a non-empty array")

        deduped_ids: list[str] = []
        seen: set[str] = set()
        for raw in ids_raw:
            page_id = self._required_id(raw, "arguments.page_ids[]")
            if page_id not in seen:
                seen.add(page_id)
                deduped_ids.append(page_id)
        if len(deduped_ids) > 50:
            raise ValueError("arguments.page_ids supports up to 50 ids")

        include_body = self._parse_bool(arguments.get("include_body"), default=False)
        runtime = self._runtime_config(config)
        limit = min(runtime["max_items"], len(deduped_ids))

        client = self._build_client(config)
        params: dict[str, Any] = {"id": deduped_ids, "limit": limit}
        if include_body:
            params["body-format"] = "storage"
        payload = client.get_json(path="/api/v2/pages", params=params)

        raw_items = self._extract_items(payload)
        normalized_items = [
            self._normalize_page(item, include_body=include_body, max_content_chars=runtime["max_content_chars"])
            for item in raw_items[:limit]
        ]
        found_ids = {item.get("id") for item in normalized_items if item.get("id")}
        not_found = [page_id for page_id in deduped_ids if page_id not in found_ids]

        return SkillResult(
            ok=True,
            output={
                "items": normalized_items,
                "not_found_ids": not_found,
                "count": len(normalized_items),
                "truncated": len(raw_items) > len(normalized_items),
            },
        )

    def _list_confluence_spaces(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        runtime = self._runtime_config(config)
        limit = self._effective_limit(arguments, runtime)
        cursor = self._optional_str(arguments.get("cursor"))
        keys = arguments.get("keys")

        client = self._build_client(config)
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if isinstance(keys, list) and keys:
            params["keys"] = [str(key) for key in keys if str(key).strip()]

        payload = client.get_json(path="/api/v2/spaces", params=params)
        raw_items = self._extract_items(payload)
        normalized = [self._normalize_space(item) for item in raw_items[:limit]]

        return SkillResult(
            ok=True,
            output={
                "items": normalized,
                "count": len(normalized),
                "next_cursor": self._extract_next_cursor(payload),
                "truncated": len(raw_items) > len(normalized),
            },
        )

    def _list_confluence_pages(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        space_id = self._required_id(arguments.get("space_id"), "arguments.space_id")
        parent_id = self._optional_id(arguments.get("parent_id"))
        status = self._optional_str(arguments.get("status")) or "current"
        runtime = self._runtime_config(config)
        limit = self._effective_limit(arguments, runtime)
        cursor = self._optional_str(arguments.get("cursor"))

        client = self._build_client(config)
        params: dict[str, Any] = {
            "space-id": space_id,
            "status": status,
            "limit": limit,
        }
        if parent_id:
            params["parent-id"] = parent_id
        if cursor:
            params["cursor"] = cursor

        payload = client.get_json(path="/api/v2/pages", params=params)
        raw_items = self._extract_items(payload)
        normalized = [
            self._normalize_page(item, include_body=False, max_content_chars=runtime["max_content_chars"])
            for item in raw_items[:limit]
        ]

        return SkillResult(
            ok=True,
            output={
                "items": normalized,
                "count": len(normalized),
                "next_cursor": self._extract_next_cursor(payload),
                "truncated": len(raw_items) > len(normalized),
            },
        )

    def _get_page_tree(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        root_page_id = self._required_id(arguments.get("root_page_id"), "arguments.root_page_id")
        include_root = self._parse_bool(arguments.get("include_root"), default=True)
        max_depth = self._parse_int(arguments.get("max_depth"), default=5)
        max_depth = max(0, min(max_depth, 20))

        runtime = self._runtime_config(config)
        max_nodes = runtime["max_tree_nodes"]
        client = self._build_client(config)

        nodes: list[dict[str, Any]] = []
        queue: deque[tuple[str, int, str | None]] = deque([(root_page_id, 0, None)])
        truncated = False

        while queue and len(nodes) < max_nodes:
            page_id, depth, parent_id = queue.popleft()
            page = self._fetch_page(page_id=page_id, include_body=False, config=config)

            if include_root or depth > 0:
                nodes.append(
                    {
                        "id": str(page.get("id") or page_id),
                        "title": self._string_or_none(page.get("title")),
                        "parent_id": self._string_or_none(page.get("parentId") or parent_id),
                        "depth": depth,
                    }
                )
                if len(nodes) >= max_nodes:
                    truncated = True
                    break

            if depth >= max_depth:
                continue

            child_params = {
                "parent-id": str(page.get("id") or page_id),
                "limit": min(runtime["max_items"], 100),
                "status": "current",
            }
            child_payload = client.get_json(path="/api/v2/pages", params=child_params)
            children = self._extract_items(child_payload)
            for child in children:
                child_id = self._optional_id(child.get("id"))
                if child_id:
                    queue.append((child_id, depth + 1, str(page.get("id") or page_id)))
            if self._extract_next_cursor(child_payload):
                truncated = True

        if queue:
            truncated = True

        return SkillResult(
            ok=True,
            output={
                "root_page_id": root_page_id,
                "nodes": nodes,
                "count": len(nodes),
                "truncated": truncated,
            },
        )

    def _create_confluence_page(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        space_id = self._required_id(arguments.get("space_id"), "arguments.space_id")
        title = self._required_str(arguments.get("title"), "arguments.title")
        body_storage = self._required_str(arguments.get("body_storage"), "arguments.body_storage")
        parent_id = self._optional_id(arguments.get("parent_id"))
        status = self._optional_str(arguments.get("status")) or "current"

        client = self._build_client(config)
        payload = {
            "spaceId": space_id,
            "status": status,
            "title": title,
            "body": {
                "representation": "storage",
                "value": body_storage,
            },
        }
        if parent_id:
            payload["parentId"] = parent_id

        created = client.post_json(path="/api/v2/pages", json_body=payload)
        normalized = self._normalize_page(created, include_body=False, max_content_chars=self._runtime_config(config)["max_content_chars"])
        return SkillResult(ok=True, output={"page": normalized})

    def _update_confluence_page(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        page_id = self._required_id(arguments.get("page_id"), "arguments.page_id")
        title_input = self._optional_str(arguments.get("title"))
        body_input = self._optional_str(arguments.get("body_storage"))
        explicit_version = arguments.get("version")

        if title_input is None and body_input is None:
            raise ValueError("arguments.title or arguments.body_storage is required")

        current_page = self._fetch_page(page_id=page_id, include_body=True, config=config)
        current_title = self._string_or_none(current_page.get("title")) or ""
        current_body = self._extract_body_storage(current_page) or ""
        current_version = self._extract_version_number(current_page)

        next_version = self._parse_int(explicit_version, default=current_version + 1)
        if next_version <= 0:
            raise ValueError("arguments.version must be a positive integer")

        update_payload: dict[str, Any] = {
            "id": page_id,
            "status": self._string_or_none(current_page.get("status")) or "current",
            "title": title_input if title_input is not None else current_title,
            "body": {
                "representation": "storage",
                "value": body_input if body_input is not None else current_body,
            },
            "version": {"number": next_version},
        }

        if current_page.get("spaceId") is not None:
            update_payload["spaceId"] = str(current_page.get("spaceId"))
        parent_id = self._optional_id(current_page.get("parentId"))
        if parent_id:
            update_payload["parentId"] = parent_id

        client = self._build_client(config)
        updated = client.put_json(path=f"/api/v2/pages/{page_id}", json_body=update_payload)
        normalized = self._normalize_page(updated, include_body=False, max_content_chars=self._runtime_config(config)["max_content_chars"])
        return SkillResult(ok=True, output={"page": normalized})

    def _append_confluence_page(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        page_id = self._required_id(arguments.get("page_id"), "arguments.page_id")
        append_storage = self._required_str(arguments.get("append_storage"), "arguments.append_storage")
        separator = self._optional_str(arguments.get("separator"))
        if separator is None:
            separator = "\n"

        current_page = self._fetch_page(page_id=page_id, include_body=True, config=config)
        current_title = self._string_or_none(current_page.get("title")) or ""
        current_body = self._extract_body_storage(current_page) or ""
        current_version = self._extract_version_number(current_page)

        new_body = f"{current_body}{separator}{append_storage}" if current_body else append_storage
        update_payload: dict[str, Any] = {
            "id": page_id,
            "status": self._string_or_none(current_page.get("status")) or "current",
            "title": current_title,
            "body": {
                "representation": "storage",
                "value": new_body,
            },
            "version": {"number": current_version + 1},
        }

        if current_page.get("spaceId") is not None:
            update_payload["spaceId"] = str(current_page.get("spaceId"))
        parent_id = self._optional_id(current_page.get("parentId"))
        if parent_id:
            update_payload["parentId"] = parent_id

        client = self._build_client(config)
        updated = client.put_json(path=f"/api/v2/pages/{page_id}", json_body=update_payload)
        normalized = self._normalize_page(updated, include_body=False, max_content_chars=self._runtime_config(config)["max_content_chars"])
        return SkillResult(ok=True, output={"page": normalized, "appended_chars": len(append_storage)})

    def _build_client(self, skill_config: dict[str, Any]) -> ConfluenceClient:
        runtime = self._runtime_config(skill_config)
        client_config = ConfluenceClientConfig(
            url=runtime["url"],
            timeout_sec=runtime["timeout_sec"],
            retry_attempts=runtime["retry_attempts"],
            retry_sleep_sec=runtime["retry_sleep_sec"],
        )
        return ConfluenceClient(config=client_config, username=runtime["username"], token=runtime["token"])

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
            "max_tree_nodes": self._clamp_int(
                skill_config.get("max_tree_nodes"),
                default=DEFAULT_MAX_TREE_NODES,
                minimum=1,
                maximum=1000,
            ),
        }

    def _fetch_page(self, *, page_id: str, include_body: bool, config: dict[str, Any]) -> dict[str, Any]:
        client = self._build_client(config)
        params: dict[str, Any] = {}
        if include_body:
            params["body-format"] = "storage"
        return client.get_json(path=f"/api/v2/pages/{page_id}", params=params)

    def _normalize_search_hit(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        space = payload.get("space") if isinstance(payload.get("space"), dict) else {}
        url = None
        links = payload.get("_links")
        if isinstance(links, dict):
            url = links.get("webui")
        if url is None and isinstance(content.get("_links"), dict):
            url = content.get("_links", {}).get("webui")
        return {
            "id": self._string_or_none(payload.get("id") or content.get("id")),
            "title": self._string_or_none(payload.get("title") or content.get("title")),
            "type": self._string_or_none(payload.get("entityType") or payload.get("type") or content.get("type")),
            "space_id": self._string_or_none(payload.get("spaceId") or space.get("id") or content.get("spaceId")),
            "space_key": self._string_or_none(payload.get("spaceKey") or space.get("key") or content.get("spaceKey")),
            "url": self._string_or_none(url),
        }

    def _normalize_space(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self._string_or_none(payload.get("id")),
            "key": self._string_or_none(payload.get("key")),
            "name": self._string_or_none(payload.get("name")),
            "type": self._string_or_none(payload.get("type")),
        }

    def _normalize_page(self, payload: dict[str, Any], *, include_body: bool, max_content_chars: int) -> dict[str, Any]:
        body_storage = self._extract_body_storage(payload) if include_body else None
        clipped_body = body_storage
        body_truncated = False
        if body_storage is not None and len(body_storage) > max_content_chars:
            clipped_body = body_storage[:max_content_chars]
            body_truncated = True

        normalized = {
            "id": self._string_or_none(payload.get("id")),
            "title": self._string_or_none(payload.get("title")),
            "status": self._string_or_none(payload.get("status")),
            "space_id": self._string_or_none(payload.get("spaceId") or self._nested_get(payload, ["space", "id"])),
            "parent_id": self._string_or_none(payload.get("parentId") or self._nested_get(payload, ["parent", "id"])),
            "version": self._extract_version_number(payload),
            "updated_at": self._string_or_none(payload.get("updatedAt") or self._nested_get(payload, ["version", "createdAt"])),
            "url": self._string_or_none(self._nested_get(payload, ["_links", "webui"])),
        }

        if include_body:
            normalized["body_storage"] = clipped_body or ""
            normalized["body_truncated"] = body_truncated

        return normalized

    def _extract_body_storage(self, payload: dict[str, Any]) -> str | None:
        body = payload.get("body")
        if isinstance(body, dict):
            storage = body.get("storage")
            if isinstance(storage, dict):
                value = storage.get("value")
                if isinstance(value, str):
                    return value
            value = body.get("value")
            if isinstance(value, str):
                return value
        return None

    def _extract_version_number(self, payload: dict[str, Any]) -> int:
        version = payload.get("version")
        if isinstance(version, dict):
            number = version.get("number")
            if isinstance(number, int):
                return number
            if isinstance(number, str) and number.isdigit():
                return int(number)
        if isinstance(version, int):
            return version
        return 0

    def _extract_items(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _extract_next_cursor(self, payload: dict[str, Any]) -> str | None:
        cursor = payload.get("cursor") or payload.get("nextCursor")
        if isinstance(cursor, str) and cursor.strip():
            return cursor

        links = payload.get("_links")
        if isinstance(links, dict):
            for key in ("next", "nextCursor"):
                value = links.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    def _effective_limit(self, arguments: dict[str, Any], runtime: dict[str, Any]) -> int:
        request_limit = self._parse_int(arguments.get("limit"), default=runtime["max_items"])
        request_limit = max(1, request_limit)
        return min(request_limit, runtime["max_items"])

    def _required_str(self, value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} is required")
        return value.strip()

    def _optional_str(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped if stripped else None

    def _required_id(self, value: Any, field_name: str) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(f"{field_name} is required")

    def _optional_id(self, value: Any) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _parse_bool(self, value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "y"}:
                return True
            if lowered in {"0", "false", "no", "n"}:
                return False
        return default

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

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _nested_get(self, payload: dict[str, Any], path: list[str]) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _is_valid_confluence_url(self, value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            return False
        if not parsed.netloc.endswith(".atlassian.net"):
            return False
        return parsed.path.rstrip("/") == "/wiki"

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

    def _resolve_config_path(self, config: dict[str, Any]) -> Path:
        raw_path = config.get("config_path")
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path.strip()).expanduser()
        return Path(__file__).resolve().parent / DEFAULT_CONFIG_FILENAME


def create_skill() -> ConfluenceSkill:
    return ConfluenceSkill()
