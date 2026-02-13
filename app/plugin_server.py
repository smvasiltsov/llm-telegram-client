from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import unquote

from app.storage import Storage


@dataclass(frozen=True)
class PluginServerConfig:
    host: str
    port: int
    enabled: bool


def _make_handler(storage: Storage) -> type[BaseHTTPRequestHandler]:
    class PluginHandler(BaseHTTPRequestHandler):
        server_version = "PluginTextServer/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            logging.getLogger("plugin_server").info("%s - %s", self.address_string(), format % args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            path = unquote(self.path.split("?", 1)[0]).strip("/")
            parts = [p for p in path.split("/") if p]
            if len(parts) < 3 or parts[0] != "plugins":
                self._send(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}', "application/json")
                return

            plugin_id = parts[1]
            text_id = parts[2]
            wants_view = len(parts) > 3 and parts[3] == "view"
            record = storage.get_plugin_text(plugin_id, text_id)
            if not record:
                self._send(HTTPStatus.NOT_FOUND, b'{"error":"not_found"}', "application/json")
                return

            if wants_view:
                text = record["text"]
                body = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>Ответ</title>"
                    "<style>body{font-family:Arial,Helvetica,sans-serif;padding:16px}"
                    "pre{white-space:pre-wrap;word-break:break-word}</style>"
                    "</head><body><pre>"
                    + text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    + "</pre></body></html>"
                ).encode("utf-8")
                self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
                return

            payload = {
                "id": record["text_id"],
                "plugin_id": record["plugin_id"],
                "text": record["text"],
                "created_at": record["created_at"],
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(HTTPStatus.OK, body, "application/json; charset=utf-8")

    return PluginHandler


class PluginTextServer:
    def __init__(self, storage: Storage, config: PluginServerConfig) -> None:
        self._storage = storage
        self._config = config
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._logger = logging.getLogger("plugin_server")

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def start(self) -> None:
        if not self._config.enabled:
            self._logger.info("Plugin server disabled")
            return
        handler = _make_handler(self._storage)
        self._server = ThreadingHTTPServer((self._config.host, self._config.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self._logger.info("Plugin server started http://%s:%s", self._config.host, self._config.port)

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._logger.info("Plugin server stopped")
