from __future__ import annotations

import ipaddress
import json
import socket
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from skills_sdk.contract import SkillContext, SkillResult, SkillSpec

from urllib.error import HTTPError, URLError

DEFAULT_CACHE_TTL_SEC = 300
DEFAULT_REQUEST_TIMEOUT_SEC = 10
DEFAULT_RETRY_ATTEMPTS = 2
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_SPEC_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_OPERATIONS = 5000
SUPPORTED_HTTP_METHODS: tuple[str, ...] = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"


class OpenAPINetworkError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class _SecureRedirectHandler(HTTPRedirectHandler):
    def __init__(
        self,
        max_redirects: int,
        https_only: bool,
        allow_localhost: bool,
        allow_private_network: bool,
    ):
        super().__init__()
        self._max_redirects = max_redirects
        self._https_only = https_only
        self._allow_localhost = allow_localhost
        self._allow_private_network = allow_private_network

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirects = int(getattr(req, "_redirect_count", 0)) + 1
        if redirects > self._max_redirects:
            raise HTTPError(newurl, code, "redirect_limit_exceeded", headers, fp)
        McpOpenApiIndexerSkill.validate_target_url_security(
            raw_url=newurl,
            https_only=self._https_only,
            allow_localhost=self._allow_localhost,
            allow_private_network=self._allow_private_network,
        )
        next_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if next_req is not None:
            setattr(next_req, "_redirect_count", redirects)
        return next_req


class McpOpenApiIndexerSkill:
    _INDEX_CACHE: dict[str, dict[str, Any]] = {}

    def describe(self) -> SkillSpec:
        description = (
            "OpenAPI 3.x indexer for {base_url}/openapi.json. "
            "Use arguments.mode to select operation: "
            "index, search, or batch_describe. "
            "Input contracts: "
            "index => {mode:'index', refresh?:bool}. "
            "search => {mode:'search', query:string, path_prefix?:string|string[], limit?:int}. "
            "batch_describe => {mode:'batch_describe', endpoints:[{path:string, method:string}], "
            "max_schema_depth?:int}. "
            "Output contracts (machine-first JSON): "
            "index => {spec:{title,version,openapi}, counts:{paths,operations}, operations:[...], "
            "cache:{cache_hit,ttl_sec}}. "
            "search => {query, filters:{path_prefix}, total_matches, items:[...], "
            "cache:{cache_hit,ttl_sec}}. "
            "batch_describe => {found:[{path,method,operation,input,output}], not_found:[...], "
            "summary:{requested,found,not_found}, cache:{cache_hit,ttl_sec}}. "
            "Error codes: invalid_config, network_error, parse_error, not_found, partial_success. "
            "parse_error is used for invalid spec and unsupported OpenAPI versions "
            "(not_supported_version when openapi is not 3.x)."
        )
        input_schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["index", "search", "batch_describe"]},
                "refresh": {"type": "boolean", "default": False},
                "query": {"type": "string", "minLength": 1},
                "path_prefix": {
                    "oneOf": [
                        {"type": "string", "minLength": 1},
                        {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                            "uniqueItems": True,
                        },
                    ]
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                "endpoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "minLength": 1},
                            "method": {
                                "type": "string",
                                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"],
                            },
                        },
                        "required": ["path", "method"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                },
                "max_schema_depth": {"type": "integer", "minimum": 1, "maximum": 8, "default": 3},
            },
            "required": ["mode"],
            "oneOf": [
                {"properties": {"mode": {"const": "index"}}, "required": ["mode"]},
                {
                    "properties": {"mode": {"const": "search"}},
                    "required": ["mode", "query"],
                },
                {
                    "properties": {"mode": {"const": "batch_describe"}},
                    "required": ["mode", "endpoints"],
                },
            ],
            "additionalProperties": False,
        }
        return SkillSpec(
            skill_id="mcp.openapi_indexer",
            name="MCP OpenAPI Indexer",
            version="0.1.0",
            description=description,
            input_schema=input_schema,
            mode="read_only",
            timeout_sec=20,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        resolved, load_errors = self._load_merged_config(config)
        if load_errors:
            return load_errors
        return self._validate_resolved_config(resolved)

    def _validate_resolved_config(self, config: dict[str, Any]) -> list[str]:
        if not isinstance(config, dict):
            return ["resolved config must be an object"]

        errors: list[str] = []

        base_url = config.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            errors.append("config.base_url is required and must be a non-empty string")
            return errors

        parsed = self._parse_base_url(base_url.strip())
        if parsed is None:
            errors.append("config.base_url must be a valid absolute URL")
            return errors

        https_only = self._parse_bool(config, "https_only", default=True, errors=errors)
        allow_localhost = self._parse_bool(config, "allow_localhost", default=False, errors=errors)
        allow_private_network = self._parse_bool(config, "allow_private_network", default=False, errors=errors)

        if https_only and parsed.scheme != "https":
            errors.append("config.base_url must use https when https_only=true")
        if parsed.scheme not in {"http", "https"}:
            errors.append("config.base_url scheme must be http or https")
        if parsed.username or parsed.password:
            errors.append("config.base_url must not include userinfo credentials")
        if parsed.query or parsed.fragment:
            errors.append("config.base_url must not include query or fragment")

        host = (parsed.hostname or "").strip().lower()
        if not host:
            errors.append("config.base_url must include hostname")
        else:
            if not allow_localhost and self._is_localhost_name(host):
                errors.append("config.base_url localhost hosts are blocked by default")

            ip_obj = self._parse_ip(host)
            if ip_obj is not None:
                if not allow_localhost and ip_obj.is_loopback:
                    errors.append("config.base_url loopback addresses are blocked by default")
                if not allow_private_network and self._is_restricted_ip(ip_obj):
                    errors.append("config.base_url private or restricted IP addresses are blocked by default")

        bearer_token = config.get("bearer_token")
        if bearer_token is not None and not isinstance(bearer_token, str):
            errors.append("config.bearer_token must be a string when provided")

        api_key = config.get("api_key")
        if api_key is not None and not isinstance(api_key, str):
            errors.append("config.api_key must be a string when provided")

        bearer_present = isinstance(bearer_token, str) and bool(bearer_token.strip())
        api_key_present = isinstance(api_key, str) and bool(api_key.strip())
        if bearer_present and api_key_present:
            errors.append("only one auth method is allowed: bearer_token or api_key")

        self._parse_int(
            config,
            "cache_ttl_sec",
            default=DEFAULT_CACHE_TTL_SEC,
            minimum=1,
            maximum=86400,
            errors=errors,
        )
        self._parse_int(
            config,
            "request_timeout_sec",
            default=DEFAULT_REQUEST_TIMEOUT_SEC,
            minimum=1,
            maximum=120,
            errors=errors,
        )
        self._parse_int(
            config,
            "retry_attempts",
            default=DEFAULT_RETRY_ATTEMPTS,
            minimum=0,
            maximum=10,
            errors=errors,
        )
        self._parse_int(
            config,
            "max_redirects",
            default=DEFAULT_MAX_REDIRECTS,
            minimum=0,
            maximum=10,
            errors=errors,
        )
        self._parse_int(
            config,
            "max_spec_bytes",
            default=DEFAULT_MAX_SPEC_BYTES,
            minimum=1024,
            maximum=50 * 1024 * 1024,
            errors=errors,
        )
        self._parse_int(
            config,
            "max_operations",
            default=DEFAULT_MAX_OPERATIONS,
            minimum=1,
            maximum=20000,
            errors=errors,
        )
        return errors

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        _ = ctx
        if not isinstance(arguments, dict):
            return self._error_result(error="parse_error", reason="invalid_arguments", metadata={"detail": "arguments"})

        resolved_config, load_errors = self._load_merged_config(config)
        if load_errors:
            return self._error_result(
                error="invalid_config",
                reason="config_load_failed",
                metadata={"validation_errors": load_errors},
            )

        config_errors = self._validate_resolved_config(resolved_config)
        if config_errors:
            return self._error_result(
                error="invalid_config", reason="config_validation_failed", metadata={"validation_errors": config_errors}
            )

        mode = arguments.get("mode")
        if mode == "index":
            refresh_raw = arguments.get("refresh", False)
            refresh = refresh_raw if isinstance(refresh_raw, bool) else False
            try:
                index_payload, _source_doc, metadata = self._get_or_build_index(config=resolved_config, refresh=refresh)
            except OpenAPINetworkError as exc:
                return self._error_result(error="network_error", reason=str(exc), metadata=exc.details)
            except ValueError as exc:
                reason = str(exc)
                return self._error_result(error="parse_error", reason=reason)

            return SkillResult(
                ok=True,
                output=index_payload,
                metadata=self._success_metadata(
                    metadata=metadata,
                    reason="ok",
                    counts=index_payload.get("counts") if isinstance(index_payload.get("counts"), dict) else None,
                ),
            )
        if mode == "search":
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip():
                return self._error_result(error="parse_error", reason="query_required")

            refresh_raw = arguments.get("refresh", False)
            refresh = refresh_raw if isinstance(refresh_raw, bool) else False
            try:
                index_payload, _source_doc, metadata = self._get_or_build_index(config=resolved_config, refresh=refresh)
            except OpenAPINetworkError as exc:
                return self._error_result(error="network_error", reason=str(exc), metadata=exc.details)
            except ValueError as exc:
                reason = str(exc)
                return self._error_result(error="parse_error", reason=reason)

            limit_raw = arguments.get("limit", 20)
            limit = 20 if not isinstance(limit_raw, int) or isinstance(limit_raw, bool) else max(1, min(200, limit_raw))
            prefixes = self._normalize_path_prefixes(arguments.get("path_prefix"))

            total_matches, scored_items = self._search_operations(
                operations=index_payload.get("operations", []),
                query=query,
                prefixes=prefixes,
                limit=limit,
            )
            return SkillResult(
                ok=True,
                output={
                    "query": query.strip(),
                    "filters": {"path_prefix": prefixes},
                    "total_matches": total_matches,
                    "items": scored_items,
                },
                metadata=self._success_metadata(
                    metadata=metadata,
                    reason="ok",
                    counts={"returned": len(scored_items), "total_matches": total_matches},
                ),
            )
        if mode == "batch_describe":
            endpoints_raw = arguments.get("endpoints")
            if not isinstance(endpoints_raw, list) or not endpoints_raw:
                return self._error_result(error="parse_error", reason="endpoints_required")
            max_depth_raw = arguments.get("max_schema_depth", 3)
            max_depth = 3
            if isinstance(max_depth_raw, int) and not isinstance(max_depth_raw, bool):
                max_depth = max(1, min(8, max_depth_raw))

            refresh_raw = arguments.get("refresh", False)
            refresh = refresh_raw if isinstance(refresh_raw, bool) else False
            try:
                index_payload, source_doc, metadata = self._get_or_build_index(config=resolved_config, refresh=refresh)
            except OpenAPINetworkError as exc:
                return self._error_result(error="network_error", reason=str(exc), metadata=exc.details)
            except ValueError as exc:
                reason = str(exc)
                return self._error_result(error="parse_error", reason=reason)

            found, not_found = self._batch_describe(
                endpoints=endpoints_raw,
                operations=index_payload.get("operations", []),
                source_doc=source_doc,
                max_depth=max_depth,
            )
            summary_counts = {"requested": len(endpoints_raw), "found": len(found), "not_found": len(not_found)}
            output = {
                "found": found,
                "not_found": not_found,
                "summary": summary_counts,
            }
            if found and not_found:
                return self._error_result(
                    error="partial_success",
                    reason="partial_success",
                    metadata=metadata,
                    output=output,
                    counts=summary_counts,
                )
            if not found:
                return self._error_result(
                    error="not_found", reason="no_matching_endpoints", metadata=metadata, output=output, counts=summary_counts
                )
            return SkillResult(
                ok=True,
                output=output,
                metadata=self._success_metadata(metadata=metadata, reason="ok", counts=summary_counts),
            )

        return self._error_result(error="parse_error", reason="unsupported_mode")

    def _load_merged_config(self, runtime_config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        if not isinstance(runtime_config, dict):
            return {}, ["config must be an object"]
        file_config, file_errors = self._load_default_config_file()
        if file_errors:
            return {}, file_errors
        merged = dict(file_config)
        merged.update(runtime_config)
        return merged, []

    def _load_default_config_file(self) -> tuple[dict[str, Any], list[str]]:
        if not DEFAULT_CONFIG_PATH.exists():
            return {}, []
        try:
            raw = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            return {}, [f"config file read failed: {DEFAULT_CONFIG_PATH}: {exc}"]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {}, [f"config file is not valid JSON: {DEFAULT_CONFIG_PATH}: {exc.msg}"]
        if not isinstance(parsed, dict):
            return {}, [f"config file must contain an object: {DEFAULT_CONFIG_PATH}"]
        return parsed, []

    def _error_result(
        self,
        error: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        counts: dict[str, int] | None = None,
    ) -> SkillResult:
        return SkillResult(
            ok=False,
            error=error,
            output=output or {},
            metadata=self._normalize_metadata(metadata=metadata, reason=reason, counts=counts),
        )

    def _success_metadata(
        self,
        metadata: dict[str, Any] | None,
        reason: str,
        counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return self._normalize_metadata(metadata=metadata, reason=reason, counts=counts)

    @staticmethod
    def _normalize_metadata(
        metadata: dict[str, Any] | None,
        reason: str,
        counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        raw = dict(metadata or {})
        cache_hit = bool(raw.pop("cache_hit", False))
        cache_age_raw = raw.pop("cache_age_sec", 0)
        cache_age_sec = cache_age_raw if isinstance(cache_age_raw, int) and cache_age_raw >= 0 else 0
        cache_source = raw.pop("source", "network")

        elapsed_ms_raw = raw.pop("elapsed_ms", None)
        timings: dict[str, Any] = {}
        if isinstance(elapsed_ms_raw, int) and elapsed_ms_raw >= 0:
            timings["elapsed_ms"] = elapsed_ms_raw

        source = None
        source_url = raw.pop("source_url", None)
        url = raw.pop("url", None)
        if isinstance(source_url, str) and source_url:
            source = source_url
        elif isinstance(url, str) and url:
            source = url

        normalized: dict[str, Any] = {
            "reason": reason,
            "counts": counts or {},
            "timings": timings,
            "cache": {"cache_hit": cache_hit, "cache_age_sec": cache_age_sec, "source": cache_source},
        }
        if source is not None:
            normalized["source"] = source
        if raw:
            normalized["details"] = raw
        return normalized

    def _fetch_openapi_json(self, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized_base = self._normalize_base_url(str(config.get("base_url", "")))
        openapi_url = f"{normalized_base}/openapi.json"

        timeout_sec = int(config.get("request_timeout_sec", DEFAULT_REQUEST_TIMEOUT_SEC))
        retry_attempts = int(config.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS))
        max_redirects = int(config.get("max_redirects", DEFAULT_MAX_REDIRECTS))
        max_spec_bytes = int(config.get("max_spec_bytes", DEFAULT_MAX_SPEC_BYTES))

        https_only = bool(config.get("https_only", True))
        allow_localhost = bool(config.get("allow_localhost", False))
        allow_private_network = bool(config.get("allow_private_network", False))

        headers = {
            "Accept": "application/json",
            "User-Agent": "mcp-openapi-indexer/0.1.0",
        }
        bearer_token = config.get("bearer_token")
        api_key = config.get("api_key")
        if isinstance(bearer_token, str) and bearer_token.strip():
            headers["Authorization"] = f"Bearer {bearer_token.strip()}"
        if isinstance(api_key, str) and api_key.strip():
            headers["x-api-key"] = api_key.strip()

        redirect_handler = _SecureRedirectHandler(
            max_redirects=max_redirects,
            https_only=https_only,
            allow_localhost=allow_localhost,
            allow_private_network=allow_private_network,
        )
        opener = build_opener(redirect_handler)

        last_error: str | None = None
        started_at = time.time()
        total_attempts = retry_attempts + 1

        for attempt in range(1, total_attempts + 1):
            request = Request(openapi_url, method="GET", headers=headers)
            try:
                with opener.open(request, timeout=timeout_sec) as response:
                    final_url = response.geturl()
                    self.validate_target_url_security(
                        raw_url=final_url,
                        https_only=https_only,
                        allow_localhost=allow_localhost,
                        allow_private_network=allow_private_network,
                    )

                    body = response.read(max_spec_bytes + 1)
                    if len(body) > max_spec_bytes:
                        raise OpenAPINetworkError(
                            "response_too_large",
                            {
                                "url": final_url,
                                "max_spec_bytes": max_spec_bytes,
                                "attempt": attempt,
                                "attempts_total": total_attempts,
                            },
                        )
                    try:
                        parsed = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise OpenAPINetworkError(
                            "invalid_json",
                            {
                                "url": final_url,
                                "attempt": attempt,
                                "attempts_total": total_attempts,
                                "detail": str(exc),
                            },
                        ) from exc

                    if not isinstance(parsed, dict):
                        raise OpenAPINetworkError(
                            "invalid_document_type",
                            {
                                "url": final_url,
                                "attempt": attempt,
                                "attempts_total": total_attempts,
                                "type": type(parsed).__name__,
                            },
                        )

                    elapsed_ms = int((time.time() - started_at) * 1000)
                    metadata = {
                        "url": final_url,
                        "attempt": attempt,
                        "attempts_total": total_attempts,
                        "elapsed_ms": elapsed_ms,
                    }
                    return parsed, metadata
            except OpenAPINetworkError:
                raise
            except HTTPError as exc:
                if 500 <= exc.code <= 599 and attempt < total_attempts:
                    last_error = f"http_{exc.code}"
                    continue
                raise OpenAPINetworkError(
                    "http_error",
                    {
                        "url": openapi_url,
                        "status_code": exc.code,
                        "attempt": attempt,
                        "attempts_total": total_attempts,
                        "detail": str(exc),
                    },
                ) from exc
            except (URLError, TimeoutError, socket.timeout, OSError) as exc:
                last_error = str(exc)
                if attempt < total_attempts:
                    continue
                raise OpenAPINetworkError(
                    "transport_error",
                    {
                        "url": openapi_url,
                        "attempt": attempt,
                        "attempts_total": total_attempts,
                        "detail": str(exc),
                    },
                ) from exc

        raise OpenAPINetworkError(
            "transport_error",
            {"url": openapi_url, "attempts_total": total_attempts, "detail": last_error or "unknown"},
        )

    def _get_or_build_index(self, config: dict[str, Any], refresh: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        ttl_sec = int(config.get("cache_ttl_sec", DEFAULT_CACHE_TTL_SEC))
        cache_key = self._cache_key(config)
        now = time.time()
        cached = self._INDEX_CACHE.get(cache_key)

        if not refresh and cached is not None:
            age_sec = max(0, int(now - float(cached.get("stored_at", now))))
            if age_sec <= ttl_sec:
                metadata = {
                    "cache_hit": True,
                    "cache_age_sec": age_sec,
                    "source": "cache",
                    "source_url": cached.get("source_url"),
                }
                return deepcopy(cached["index_payload"]), deepcopy(cached["source_doc"]), metadata

        doc, fetch_metadata = self._fetch_openapi_json(config)
        index_payload = self._build_operation_index(
            doc=doc,
            max_operations=int(config.get("max_operations", DEFAULT_MAX_OPERATIONS)),
        )
        source_url = fetch_metadata.get("url")
        stored_at = time.time()
        self._INDEX_CACHE[cache_key] = {
            "index_payload": deepcopy(index_payload),
            "source_doc": deepcopy(doc),
            "stored_at": stored_at,
            "source_url": source_url,
        }
        metadata = {
            **fetch_metadata,
            "cache_hit": False,
            "cache_age_sec": 0,
            "source": "network",
            "source_url": source_url,
        }
        return index_payload, doc, metadata

    def _build_operation_index(self, doc: dict[str, Any], max_operations: int) -> dict[str, Any]:
        openapi_raw = doc.get("openapi")
        if not isinstance(openapi_raw, str) or not openapi_raw.startswith("3."):
            raise ValueError("not_supported_version")

        info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
        paths = doc.get("paths")
        if not isinstance(paths, dict):
            raise ValueError("invalid_paths_object")

        operations: list[dict[str, Any]] = []
        path_count = 0
        for raw_path, raw_item in paths.items():
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                continue
            if not isinstance(raw_item, dict):
                continue
            path_count += 1

            for http_method in SUPPORTED_HTTP_METHODS:
                raw_operation = raw_item.get(http_method)
                if not isinstance(raw_operation, dict):
                    continue
                if len(operations) >= max_operations:
                    raise ValueError("max_operations_exceeded")
                operations.append(self._build_operation_entry(path=raw_path, method=http_method, operation=raw_operation))

        return {
            "spec": {
                "title": info.get("title") if isinstance(info.get("title"), str) else None,
                "version": info.get("version") if isinstance(info.get("version"), str) else None,
                "openapi": openapi_raw,
            },
            "counts": {"paths": path_count, "operations": len(operations)},
            "operations": operations,
        }

    def _build_operation_entry(self, path: str, method: str, operation: dict[str, Any]) -> dict[str, Any]:
        tags = operation.get("tags")
        normalized_tags = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
        summary = operation.get("summary") if isinstance(operation.get("summary"), str) else ""
        description = operation.get("description") if isinstance(operation.get("description"), str) else ""
        operation_id = operation.get("operationId") if isinstance(operation.get("operationId"), str) else ""

        input_summary = self._build_input_summary(operation)
        output_summary = self._build_output_summary(operation)

        searchable_parts = [path, method.upper(), summary, description, operation_id, " ".join(normalized_tags)]
        searchable_text = " ".join([part for part in searchable_parts if part]).strip().lower()

        return {
            "path": path,
            "method": method.upper(),
            "summary": summary,
            "description": description,
            "tags": normalized_tags,
            "operation_id": operation_id,
            "input": input_summary,
            "output": output_summary,
            "searchable_text": searchable_text,
        }

    def _batch_describe(
        self,
        endpoints: list[Any],
        operations: list[Any],
        source_doc: dict[str, Any],
        max_depth: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        index_map: dict[tuple[str, str], dict[str, Any]] = {}
        for item in operations:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            method = item.get("method")
            if isinstance(path, str) and isinstance(method, str):
                index_map[(path, method.upper())] = item

        paths = source_doc.get("paths") if isinstance(source_doc.get("paths"), dict) else {}
        components = source_doc.get("components") if isinstance(source_doc.get("components"), dict) else {}

        found: list[dict[str, Any]] = []
        not_found: list[dict[str, Any]] = []
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                not_found.append({"path": None, "method": None, "reason": "invalid_endpoint_object"})
                continue
            path = endpoint.get("path")
            method = endpoint.get("method")
            if not isinstance(path, str) or not isinstance(method, str):
                not_found.append({"path": path, "method": method, "reason": "path_and_method_required"})
                continue

            method_upper = method.upper()
            index_item = index_map.get((path, method_upper))
            if index_item is None:
                not_found.append({"path": path, "method": method_upper, "reason": "operation_not_found"})
                continue

            op_obj = None
            path_item = paths.get(path)
            if isinstance(path_item, dict):
                raw_op = path_item.get(method_upper.lower())
                if isinstance(raw_op, dict):
                    op_obj = raw_op
            if op_obj is None:
                not_found.append({"path": path, "method": method_upper, "reason": "operation_definition_not_found"})
                continue

            found.append(
                {
                    "path": path,
                    "method": method_upper,
                    "summary": index_item.get("summary"),
                    "description": index_item.get("description"),
                    "tags": index_item.get("tags", []),
                    "operation_id": index_item.get("operation_id"),
                    "input": self._build_input_detail(op_obj, components=components, max_depth=max_depth),
                    "output": self._build_output_detail(op_obj, components=components, max_depth=max_depth),
                }
            )
        return found, not_found

    def _build_input_detail(self, operation: dict[str, Any], components: dict[str, Any], max_depth: int) -> dict[str, Any]:
        parameters_detail: list[dict[str, Any]] = []
        raw_parameters = operation.get("parameters")
        if isinstance(raw_parameters, list):
            for item in raw_parameters:
                if not isinstance(item, dict):
                    continue
                parameter: dict[str, Any] = {
                    "name": item.get("name"),
                    "in": item.get("in"),
                    "required": bool(item.get("required", False)),
                }
                if isinstance(item.get("$ref"), str):
                    parameter["ref"] = item.get("$ref")
                    parameter["resolved"] = self._resolve_ref(item.get("$ref"), components=components, max_depth=max_depth)
                schema = item.get("schema")
                if isinstance(schema, dict):
                    parameter["schema"] = self._expand_schema(
                        schema=schema, components=components, max_depth=max_depth, seen_refs=set()
                    )
                parameters_detail.append(parameter)

        request_body_detail: dict[str, Any] = {}
        request_body = operation.get("requestBody")
        if isinstance(request_body, dict):
            request_body_detail["required"] = bool(request_body.get("required", False))
            if isinstance(request_body.get("$ref"), str):
                request_body_detail["ref"] = request_body.get("$ref")
                request_body_detail["resolved"] = self._resolve_ref(
                    request_body.get("$ref"), components=components, max_depth=max_depth
                )
            content = request_body.get("content")
            if isinstance(content, dict):
                media: dict[str, Any] = {}
                for content_type, content_value in content.items():
                    if not isinstance(content_type, str) or not isinstance(content_value, dict):
                        continue
                    media_item: dict[str, Any] = {}
                    schema = content_value.get("schema")
                    if isinstance(schema, dict):
                        media_item["schema"] = self._expand_schema(
                            schema=schema, components=components, max_depth=max_depth, seen_refs=set()
                        )
                    media[content_type] = media_item
                if media:
                    request_body_detail["content"] = media

        return {"parameters": parameters_detail, "request_body": request_body_detail}

    def _build_output_detail(self, operation: dict[str, Any], components: dict[str, Any], max_depth: int) -> dict[str, Any]:
        responses_detail: list[dict[str, Any]] = []
        responses = operation.get("responses")
        if isinstance(responses, dict):
            for status, value in responses.items():
                if not isinstance(status, str) or not isinstance(value, dict):
                    continue
                item: dict[str, Any] = {"status": status}
                if isinstance(value.get("description"), str):
                    item["description"] = value.get("description")
                if isinstance(value.get("$ref"), str):
                    item["ref"] = value.get("$ref")
                    item["resolved"] = self._resolve_ref(value.get("$ref"), components=components, max_depth=max_depth)
                content = value.get("content")
                if isinstance(content, dict):
                    media: dict[str, Any] = {}
                    for content_type, content_value in content.items():
                        if not isinstance(content_type, str) or not isinstance(content_value, dict):
                            continue
                        media_item: dict[str, Any] = {}
                        schema = content_value.get("schema")
                        if isinstance(schema, dict):
                            media_item["schema"] = self._expand_schema(
                                schema=schema, components=components, max_depth=max_depth, seen_refs=set()
                            )
                        media[content_type] = media_item
                    if media:
                        item["content"] = media
                responses_detail.append(item)
        return {"responses": responses_detail}

    def _resolve_ref(self, ref: str, components: dict[str, Any], max_depth: int) -> dict[str, Any]:
        if max_depth <= 0:
            return {"$ref": ref, "truncated": True}
        if not ref.startswith("#/components/"):
            return {"$ref": ref, "unsupported_ref": True}

        parts = ref.lstrip("#/").split("/")
        node: Any = {"components": components}
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return {"$ref": ref, "missing_ref_target": True}
            node = node[part]
        if not isinstance(node, dict):
            return {"$ref": ref, "resolved_scalar": node}
        return self._expand_schema(schema=node, components=components, max_depth=max_depth - 1, seen_refs={ref})

    def _expand_schema(
        self,
        schema: dict[str, Any],
        components: dict[str, Any],
        max_depth: int,
        seen_refs: set[str],
    ) -> dict[str, Any]:
        if max_depth <= 0:
            return {"truncated": True}

        result: dict[str, Any] = {}
        for key in ("type", "format", "title", "description", "enum", "required", "nullable"):
            if key in schema:
                result[key] = schema.get(key)

        ref = schema.get("$ref")
        if isinstance(ref, str):
            result["$ref"] = ref
            if ref in seen_refs:
                result["cycle_detected"] = True
                return result
            if ref.startswith("#/components/"):
                next_seen = set(seen_refs)
                next_seen.add(ref)
                resolved = self._resolve_component_ref(
                    ref=ref, components=components, max_depth=max_depth - 1, seen_refs=next_seen
                )
                result["resolved"] = resolved
            return result

        properties = schema.get("properties")
        if isinstance(properties, dict):
            expanded_properties: dict[str, Any] = {}
            for prop_name, prop_schema in properties.items():
                if isinstance(prop_name, str) and isinstance(prop_schema, dict):
                    expanded_properties[prop_name] = self._expand_schema(
                        schema=prop_schema,
                        components=components,
                        max_depth=max_depth - 1,
                        seen_refs=set(seen_refs),
                    )
            if expanded_properties:
                result["properties"] = expanded_properties

        items = schema.get("items")
        if isinstance(items, dict):
            result["items"] = self._expand_schema(
                schema=items, components=components, max_depth=max_depth - 1, seen_refs=set(seen_refs)
            )

        additional_properties = schema.get("additionalProperties")
        if isinstance(additional_properties, dict):
            result["additionalProperties"] = self._expand_schema(
                schema=additional_properties,
                components=components,
                max_depth=max_depth - 1,
                seen_refs=set(seen_refs),
            )
        elif isinstance(additional_properties, bool):
            result["additionalProperties"] = additional_properties

        for key in ("allOf", "anyOf", "oneOf"):
            value = schema.get(key)
            if isinstance(value, list):
                branches: list[Any] = []
                for branch in value:
                    if isinstance(branch, dict):
                        branches.append(
                            self._expand_schema(
                                schema=branch, components=components, max_depth=max_depth - 1, seen_refs=set(seen_refs)
                            )
                        )
                if branches:
                    result[key] = branches

        return result

    def _resolve_component_ref(
        self,
        ref: str,
        components: dict[str, Any],
        max_depth: int,
        seen_refs: set[str],
    ) -> dict[str, Any]:
        if max_depth <= 0:
            return {"$ref": ref, "truncated": True}
        if not ref.startswith("#/components/"):
            return {"$ref": ref, "unsupported_ref": True}

        parts = ref.lstrip("#/").split("/")
        node: Any = {"components": components}
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return {"$ref": ref, "missing_ref_target": True}
            node = node[part]
        if not isinstance(node, dict):
            return {"$ref": ref, "resolved_scalar": node}
        return self._expand_schema(schema=node, components=components, max_depth=max_depth, seen_refs=seen_refs)

    def _build_input_summary(self, operation: dict[str, Any]) -> dict[str, Any]:
        parameters: list[dict[str, Any]] = []
        raw_parameters = operation.get("parameters")
        if isinstance(raw_parameters, list):
            for item in raw_parameters:
                if not isinstance(item, dict):
                    continue
                parameter: dict[str, Any] = {
                    "name": item.get("name") if isinstance(item.get("name"), str) else "",
                    "in": item.get("in") if isinstance(item.get("in"), str) else "",
                    "required": bool(item.get("required", False)),
                }
                schema = item.get("schema")
                if isinstance(schema, dict):
                    if isinstance(schema.get("type"), str):
                        parameter["type"] = schema.get("type")
                    refs = self._collect_schema_refs(schema)
                    if refs:
                        parameter["schema_refs"] = refs
                if isinstance(item.get("$ref"), str):
                    parameter["ref"] = item.get("$ref")
                parameters.append(parameter)

        request_body = operation.get("requestBody")
        request_body_summary: dict[str, Any] = {}
        if isinstance(request_body, dict):
            request_body_summary["required"] = bool(request_body.get("required", False))
            if isinstance(request_body.get("$ref"), str):
                request_body_summary["ref"] = request_body.get("$ref")
            content = request_body.get("content")
            if isinstance(content, dict):
                content_types: list[str] = []
                schema_refs: list[str] = []
                for content_type, content_value in content.items():
                    if not isinstance(content_type, str) or not isinstance(content_value, dict):
                        continue
                    content_types.append(content_type)
                    schema = content_value.get("schema")
                    if isinstance(schema, dict):
                        schema_refs.extend(self._collect_schema_refs(schema))
                if content_types:
                    request_body_summary["content_types"] = sorted(set(content_types))
                if schema_refs:
                    request_body_summary["schema_refs"] = sorted(set(schema_refs))

        return {
            "parameters": parameters,
            "request_body": request_body_summary,
        }

    def _build_output_summary(self, operation: dict[str, Any]) -> dict[str, Any]:
        raw_responses = operation.get("responses")
        responses: list[dict[str, Any]] = []
        if isinstance(raw_responses, dict):
            for status, value in raw_responses.items():
                if not isinstance(status, str) or not isinstance(value, dict):
                    continue
                item: dict[str, Any] = {"status": status}
                if isinstance(value.get("description"), str):
                    item["description"] = value.get("description")
                if isinstance(value.get("$ref"), str):
                    item["ref"] = value.get("$ref")
                content = value.get("content")
                if isinstance(content, dict):
                    content_types: list[str] = []
                    schema_refs: list[str] = []
                    for content_type, content_value in content.items():
                        if not isinstance(content_type, str) or not isinstance(content_value, dict):
                            continue
                        content_types.append(content_type)
                        schema = content_value.get("schema")
                        if isinstance(schema, dict):
                            schema_refs.extend(self._collect_schema_refs(schema))
                    if content_types:
                        item["content_types"] = sorted(set(content_types))
                    if schema_refs:
                        item["schema_refs"] = sorted(set(schema_refs))
                responses.append(item)

        return {"responses": responses}

    def _collect_schema_refs(self, schema: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        if isinstance(schema.get("$ref"), str):
            refs.append(schema.get("$ref"))
        items = schema.get("items")
        if isinstance(items, dict) and isinstance(items.get("$ref"), str):
            refs.append(items.get("$ref"))
        additional_properties = schema.get("additionalProperties")
        if isinstance(additional_properties, dict) and isinstance(additional_properties.get("$ref"), str):
            refs.append(additional_properties.get("$ref"))
        for key in ("allOf", "anyOf", "oneOf"):
            value = schema.get(key)
            if isinstance(value, list):
                for branch in value:
                    if isinstance(branch, dict) and isinstance(branch.get("$ref"), str):
                        refs.append(branch.get("$ref"))
        return sorted(set(refs))

    def _search_operations(
        self,
        operations: list[Any],
        query: str,
        prefixes: list[str],
        limit: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        normalized_query = query.strip().lower()
        terms = [term for term in normalized_query.split() if term]
        if not terms:
            return 0, []

        candidates: list[dict[str, Any]] = []
        for item in operations:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str):
                continue
            if prefixes and not self._matches_any_prefix(path=path, prefixes=prefixes):
                continue

            score = self._score_operation(item=item, terms=terms)
            if score <= 0:
                continue
            candidates.append({"score": score, "item": item})

        candidates.sort(
            key=lambda x: (
                -x["score"],
                str(x["item"].get("path", "")),
                str(x["item"].get("method", "")),
            )
        )
        top = candidates[:limit]

        compact_items: list[dict[str, Any]] = []
        for row in top:
            item = row["item"]
            compact_items.append(
                {
                    "path": item.get("path"),
                    "method": item.get("method"),
                    "summary": item.get("summary"),
                    "description": item.get("description"),
                    "tags": item.get("tags", []),
                    "operation_id": item.get("operation_id"),
                    "score": row["score"],
                    "input": item.get("input"),
                    "output": item.get("output"),
                }
            )
        return len(candidates), compact_items

    def _score_operation(self, item: dict[str, Any], terms: list[str]) -> int:
        path = str(item.get("path", "")).lower()
        method = str(item.get("method", "")).lower()
        summary = str(item.get("summary", "")).lower()
        description = str(item.get("description", "")).lower()
        operation_id = str(item.get("operation_id", "")).lower()
        tags = " ".join([tag for tag in item.get("tags", []) if isinstance(tag, str)]).lower()
        searchable_text = str(item.get("searchable_text", "")).lower()

        score = 0
        for term in terms:
            if term in path:
                score += 8
            if term == method:
                score += 10
            elif term in method:
                score += 6
            if term in summary:
                score += 6
            if term in description:
                score += 3
            if term in operation_id:
                score += 5
            if term in tags:
                score += 4
            if term in searchable_text:
                score += 1
        return score

    @staticmethod
    def _normalize_path_prefixes(raw: Any) -> list[str]:
        if raw is None:
            return []
        prefixes: list[str] = []
        if isinstance(raw, str):
            value = raw.strip()
            if value:
                prefixes.append(value)
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    prefixes.append(item.strip())

        normalized: list[str] = []
        seen: set[str] = set()
        for prefix in prefixes:
            normalized_prefix = prefix if prefix.startswith("/") else f"/{prefix}"
            if normalized_prefix not in seen:
                seen.add(normalized_prefix)
                normalized.append(normalized_prefix)
        return normalized

    @staticmethod
    def _matches_any_prefix(path: str, prefixes: list[str]) -> bool:
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "{"):
                return True
        return False

    @staticmethod
    def _parse_base_url(raw: str):
        try:
            return urlparse(raw)
        except ValueError:
            return None

    @staticmethod
    def _parse_bool(config: dict[str, Any], field: str, default: bool, errors: list[str]) -> bool:
        value = config.get(field, default)
        if isinstance(value, bool):
            return value
        errors.append(f"config.{field} must be boolean")
        return default

    @staticmethod
    def _parse_int(
        config: dict[str, Any],
        field: str,
        default: int,
        minimum: int,
        maximum: int,
        errors: list[str],
    ) -> int:
        value = config.get(field, default)
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"config.{field} must be an integer")
            return default
        if value < minimum or value > maximum:
            errors.append(f"config.{field} must be between {minimum} and {maximum}")
            return default
        return value

    @staticmethod
    def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    @staticmethod
    def _is_localhost_name(host: str) -> bool:
        return host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost")

    @staticmethod
    def _is_restricted_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        )

    @classmethod
    def _normalize_base_url(cls, raw_url: str) -> str:
        parsed = cls._parse_base_url(raw_url.strip())
        if parsed is None or not parsed.scheme or not parsed.netloc:
            raise OpenAPINetworkError("invalid_base_url", {"base_url": raw_url})
        normalized_path = (parsed.path or "").rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{normalized_path}"

    @classmethod
    def _cache_key(cls, config: dict[str, Any]) -> str:
        normalized_base = cls._normalize_base_url(str(config.get("base_url", "")))
        bearer_token = config.get("bearer_token")
        api_key = config.get("api_key")
        auth_fingerprint = ""
        if isinstance(bearer_token, str) and bearer_token.strip():
            auth_fingerprint = "bearer:" + sha256(bearer_token.strip().encode("utf-8")).hexdigest()
        elif isinstance(api_key, str) and api_key.strip():
            auth_fingerprint = "api_key:" + sha256(api_key.strip().encode("utf-8")).hexdigest()

        key_parts = {
            "base_url": normalized_base,
            "https_only": bool(config.get("https_only", True)),
            "allow_localhost": bool(config.get("allow_localhost", False)),
            "allow_private_network": bool(config.get("allow_private_network", False)),
            "max_spec_bytes": int(config.get("max_spec_bytes", DEFAULT_MAX_SPEC_BYTES)),
            "max_operations": int(config.get("max_operations", DEFAULT_MAX_OPERATIONS)),
            "auth": auth_fingerprint,
        }
        return json.dumps(key_parts, sort_keys=True, separators=(",", ":"))

    @classmethod
    def validate_target_url_security(
        cls,
        raw_url: str,
        https_only: bool,
        allow_localhost: bool,
        allow_private_network: bool,
    ) -> None:
        parsed = cls._parse_base_url(raw_url)
        if parsed is None:
            raise OpenAPINetworkError("invalid_url", {"url": raw_url})
        if parsed.scheme not in {"http", "https"}:
            raise OpenAPINetworkError("invalid_scheme", {"url": raw_url, "scheme": parsed.scheme})
        if https_only and parsed.scheme != "https":
            raise OpenAPINetworkError("https_required", {"url": raw_url})

        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise OpenAPINetworkError("missing_host", {"url": raw_url})
        if not allow_localhost and cls._is_localhost_name(host):
            raise OpenAPINetworkError("blocked_localhost", {"url": raw_url, "host": host})

        ip_obj = cls._parse_ip(host)
        if ip_obj is not None:
            if not allow_localhost and ip_obj.is_loopback:
                raise OpenAPINetworkError("blocked_loopback", {"url": raw_url, "host": host})
            if not allow_private_network and cls._is_restricted_ip(ip_obj):
                raise OpenAPINetworkError("blocked_private_network", {"url": raw_url, "host": host})


def create_skill() -> McpOpenApiIndexerSkill:
    return McpOpenApiIndexerSkill()
