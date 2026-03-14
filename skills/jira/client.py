from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class JiraClientError(RuntimeError):
    pass


class JiraHTTPError(JiraClientError):
    def __init__(self, *, status_code: int, message: str, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass(frozen=True)
class JiraClientConfig:
    url: str
    timeout_sec: int = 30
    retry_attempts: int = 3
    retry_sleep_sec: float = 3.0


class JiraClient:
    def __init__(self, *, config: JiraClientConfig, username: str, token: str) -> None:
        self._base_url = config.url.rstrip("/")
        self._timeout_sec = int(config.timeout_sec)
        self._retry_attempts = max(1, int(config.retry_attempts))
        self._retry_sleep_sec = max(0.0, float(config.retry_sleep_sec))
        self._auth_header = _build_basic_auth_header(username=username, token=token)

    def request_json(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = _build_url(self._base_url, path, params=params)
        payload: bytes | None = None
        request_headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        if json_body is not None:
            payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url=url, data=payload, method=method.upper(), headers=request_headers)

        for attempt in range(1, self._retry_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_sec) as response:
                    raw = response.read()
                if not raw:
                    return {}
                return _parse_json_object(raw)
            except urllib.error.HTTPError as exc:
                body = _read_http_error_body(exc)
                if exc.code in RETRYABLE_HTTP_CODES and attempt < self._retry_attempts:
                    time.sleep(self._retry_sleep_sec)
                    continue
                raise JiraHTTPError(
                    status_code=int(exc.code),
                    message=f"Jira HTTP error {exc.code}",
                    response_body=body,
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self._retry_attempts:
                    time.sleep(self._retry_sleep_sec)
                    continue
                raise JiraClientError(f"Jira request failed after {attempt} attempts: {exc}") from exc

        raise JiraClientError("Jira request failed")

    def get_json(self, *, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json(method="GET", path=path, params=params)

    def post_json(
        self,
        *,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        return self.request_json(method="POST", path=path, params=params, json_body=json_body)

    def put_json(
        self,
        *,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        return self.request_json(method="PUT", path=path, params=params, json_body=json_body)


def _build_basic_auth_header(*, username: str, token: str) -> str:
    raw = f"{username}:{token}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"Basic {encoded}"


def _build_url(base_url: str, path: str, *, params: dict[str, Any] | None = None) -> str:
    normalized_path = path.strip()
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    url = f"{base_url}{normalized_path}"
    if not params:
        return url
    encoded = urllib.parse.urlencode(_normalize_query_params(params), doseq=True)
    return f"{url}?{encoded}"


def _normalize_query_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        normalized[str(key)] = value
    return normalized


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise JiraClientError(f"Invalid JSON response: {exc}") from exc
    if isinstance(decoded, dict):
        return decoded
    return {"data": decoded}


def _read_http_error_body(exc: urllib.error.HTTPError) -> str | None:
    try:
        raw = exc.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None
