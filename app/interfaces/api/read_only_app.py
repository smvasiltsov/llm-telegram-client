from __future__ import annotations

import logging
import os
from time import monotonic

from app.application.contracts import NoopMetricsPort, build_operation_labels
from app.application.observability import correlation_scope, ensure_correlation_id, get_correlation_id
from app.interfaces.api.dependencies import (
    attach_runtime_dependencies_to_app_state,
)
from app.interfaces.api.error_mapping import map_exception_to_api_error
from app.interfaces.api.qa_dispatch_bridge_worker import build_dispatch_bridge_worker
from app.interfaces.api.thread_event_outbox_dispatcher import build_thread_event_outbox_dispatcher
from app.interfaces.api.routers import build_read_only_v1_router
from app.interfaces.api.schemas import ApiErrorBody, ApiErrorResponse

logger = logging.getLogger("api")


def _resolve_cors_origins() -> list[str]:
    # Comma-separated list, e.g. "app://obsidian.md,http://localhost:3000"
    raw = str(os.getenv("API_CORS_ALLOWED_ORIGINS", "") or "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "app://obsidian.md",
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def build_read_only_fastapi_app(runtime) -> object:
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from starlette.middleware.cors import CORSMiddleware
    except Exception as exc:  # pragma: no cover - runtime dependency gap
        raise RuntimeError(
            "FastAPI dependencies are unavailable. Install `fastapi` and `uvicorn` to run read-only API."
        ) from exc

    app = FastAPI(
        title="LLM Telegram Client Read-Only API",
        version="0.1.0",
    )
    attach_runtime_dependencies_to_app_state(app.state, runtime)
    cors_origins = _resolve_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-Id"],
    )
    logger.info("api_cors_enabled origins=%s", cors_origins)

    def _resolve_metrics_port():
        direct = getattr(app.state, "metrics_port", None)
        if hasattr(direct, "increment") and hasattr(direct, "observe_ms"):
            return direct
        runtime_obj = getattr(app.state, "runtime", None)
        runtime_metrics = getattr(runtime_obj, "metrics_port", None)
        if hasattr(runtime_metrics, "increment") and hasattr(runtime_metrics, "observe_ms"):
            return runtime_metrics
        return NoopMetricsPort()

    @app.middleware("http")
    async def _correlation_and_metrics_middleware(request: Request, call_next):  # noqa: ANN001
        incoming_corr = request.headers.get("X-Correlation-Id")
        with correlation_scope(incoming_corr) as correlation_id:
            started = monotonic()
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            logger.info(
                "api_request_started correlation_id=%s method=%s route=%s path=%s",
                correlation_id,
                request.method,
                route_path,
                request.url.path,
            )
            response = await call_next(request)
            status_code = int(getattr(response, "status_code", 500))
            operation = f"{request.method.lower()}_{route_path}"
            labels = build_operation_labels(
                operation=operation,
                transport="http",
                result=f"http_{status_code}",
            )
            metrics = _resolve_metrics_port()
            metrics.increment("api_http_requests_total", labels=labels)
            metrics.observe_ms(
                "api_http_request_latency_ms",
                value_ms=max(0.0, (monotonic() - started) * 1000.0),
                labels=labels,
            )
            http_labels = {
                "method": request.method.upper(),
                "route": str(route_path),
                "status": str(status_code),
            }
            metrics.increment("http_requests_total", labels=http_labels)
            metrics.observe_ms(
                "http_request_duration_ms",
                value_ms=max(0.0, (monotonic() - started) * 1000.0),
                labels=http_labels,
            )
            logger.info(
                "api_request_finished correlation_id=%s method=%s route=%s status=%s",
                correlation_id,
                request.method,
                route_path,
                status_code,
            )
            response.headers["X-Correlation-Id"] = correlation_id
            return response

    app.include_router(build_read_only_v1_router(app_state=app.state))

    @app.on_event("startup")
    async def _startup_dispatch_bridge() -> None:
        worker = build_dispatch_bridge_worker(getattr(app.state, "runtime", None))
        if worker is None:
            setattr(app.state, "qa_dispatch_bridge_worker", None)
        else:
            await worker.start()
            setattr(app.state, "qa_dispatch_bridge_worker", worker)
        outbox = build_thread_event_outbox_dispatcher(getattr(app.state, "runtime", None))
        if outbox is None:
            setattr(app.state, "thread_event_outbox_dispatcher", None)
            return
        await outbox.start()
        setattr(app.state, "thread_event_outbox_dispatcher", outbox)

    @app.on_event("shutdown")
    async def _shutdown_dispatch_bridge() -> None:
        outbox = getattr(app.state, "thread_event_outbox_dispatcher", None)
        if outbox is not None:
            await outbox.stop()
            setattr(app.state, "thread_event_outbox_dispatcher", None)
        worker = getattr(app.state, "qa_dispatch_bridge_worker", None)
        if worker is None:
            return
        await worker.stop()
        setattr(app.state, "qa_dispatch_bridge_worker", None)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request, exc: Exception):  # noqa: ANN001
        mapped = map_exception_to_api_error(exc)
        details = dict(mapped.payload.get("details") or {})
        details["correlation_id"] = ensure_correlation_id(get_correlation_id())
        body = ApiErrorResponse(
            error=ApiErrorBody(
                code=str(mapped.payload.get("code", "internal.unexpected")),
                message=str(mapped.payload.get("message", "Unexpected error")),
                details=details,
                retryable=bool(mapped.payload.get("retryable", False)),
            )
        )
        response = JSONResponse(status_code=int(mapped.status_code), content=body.model_dump(mode="json"))
        response.headers["X-Correlation-Id"] = ensure_correlation_id(get_correlation_id())
        return response

    return app
