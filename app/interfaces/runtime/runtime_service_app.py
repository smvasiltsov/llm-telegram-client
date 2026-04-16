from __future__ import annotations

import logging
import os

from app.application.authz import AuthzActor
from app.application.observability import correlation_scope, ensure_correlation_id
from app.interfaces.api.dependencies import (
    attach_runtime_dependencies_to_app_state,
    provide_authz_dependencies,
    provide_runtime_dispatch_health,
)
from app.interfaces.api.qa_dispatch_bridge_worker import build_dispatch_bridge_worker
from app.interfaces.api.thread_event_outbox_dispatcher import build_thread_event_outbox_dispatcher

logger = logging.getLogger("runtime_service")


def _resolve_cors_origins() -> list[str]:
    raw = str(os.getenv("RUNTIME_CORS_ALLOWED_ORIGINS", "") or "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    # Keep parity with read-only API defaults for local tooling.
    return [
        "app://obsidian.md",
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def build_runtime_service_fastapi_app(runtime) -> object:
    try:
        from fastapi import FastAPI, Header, Response
        from starlette.middleware.cors import CORSMiddleware
    except Exception as exc:  # pragma: no cover - runtime dependency gap
        raise RuntimeError(
            "FastAPI dependencies are unavailable. Install `fastapi` and `uvicorn` to run runtime service API."
        ) from exc

    app = FastAPI(
        title="LLM Runtime Service",
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
    logger.info("runtime_service_cors_enabled origins=%s", cors_origins)

    @app.middleware("http")
    async def _correlation_middleware(request, call_next):  # noqa: ANN001
        with correlation_scope(request.headers.get("X-Correlation-Id")) as correlation_id:
            response = await call_next(request)
            response.headers["X-Correlation-Id"] = ensure_correlation_id(correlation_id)
            return response

    @app.on_event("startup")
    async def _startup_worker() -> None:
        worker = build_dispatch_bridge_worker(getattr(app.state, "runtime", None))
        if worker is None:
            setattr(app.state, "runtime_dispatch_bridge_worker", None)
            logger.info("runtime_service_worker_disabled")
        else:
            await worker.start()
            setattr(app.state, "runtime_dispatch_bridge_worker", worker)
            logger.info("runtime_service_worker_started")
        outbox = build_thread_event_outbox_dispatcher(getattr(app.state, "runtime", None))
        if outbox is None:
            setattr(app.state, "runtime_thread_event_outbox_dispatcher", None)
            logger.info("runtime_service_outbox_disabled")
        else:
            await outbox.start()
            setattr(app.state, "runtime_thread_event_outbox_dispatcher", outbox)
            logger.info("runtime_service_outbox_started")

    @app.on_event("shutdown")
    async def _shutdown_worker() -> None:
        outbox = getattr(app.state, "runtime_thread_event_outbox_dispatcher", None)
        if outbox is not None:
            await outbox.stop()
            setattr(app.state, "runtime_thread_event_outbox_dispatcher", None)
            logger.info("runtime_service_outbox_stopped")
        worker = getattr(app.state, "runtime_dispatch_bridge_worker", None)
        if worker is None:
            return
        await worker.stop()
        setattr(app.state, "runtime_dispatch_bridge_worker", None)
        logger.info("runtime_service_worker_stopped")

    def _worker_snapshot() -> dict[str, object]:
        worker = getattr(app.state, "runtime_dispatch_bridge_worker", None)
        if worker is None:
            return {
                "enabled": False,
                "is_running": False,
                "pending_queue_depth": 0,
                "inflight_count": 0,
                "queued_ids_count": 0,
            }
        snap = dict(worker.snapshot())
        snap["enabled"] = True
        return snap

    def _owner_guard(user_id: int | None) -> tuple[bool, dict[str, object] | None]:
        if user_id is None:
            return False, {"code": "auth.unauthorized", "message": "Missing owner credentials"}
        authz_result = provide_authz_dependencies(app.state)
        if authz_result.is_error or authz_result.value is None:
            return False, {"code": "internal.unexpected", "message": "Authz dependencies are unavailable"}
        decision_result = authz_result.value.authz_service.authorize(
            action="http.read.owner",
            actor=AuthzActor(user_id=int(user_id)),
            resource_ctx=None,
        )
        if decision_result.is_error or decision_result.value is None or not decision_result.value.allowed:
            return False, {"code": "auth.forbidden", "message": "Owner access required"}
        return True, None

    @app.get("/health/live")
    def get_live() -> dict[str, object]:
        return {"status": "ok", "service": "runtime-service"}

    @app.get("/health/ready")
    def get_ready(response: Response) -> dict[str, object]:
        worker_state = _worker_snapshot()
        ready = bool(worker_state.get("is_running", False))
        if not ready:
            response.status_code = 503
        return {
            "status": "ready" if ready else "not_ready",
            "service": "runtime-service",
            "worker": worker_state,
        }

    @app.get("/runtime/dispatch-health")
    def get_dispatch_health(
        response: Response,
        x_owner_user_id: int | None = Header(default=None, alias="X-Owner-User-Id"),
    ) -> dict[str, object]:
        allowed, error = _owner_guard(x_owner_user_id)
        if not allowed:
            response.status_code = 401 if x_owner_user_id is None else 403
            return {"error": error or {"code": "auth.forbidden", "message": "Owner access required"}}
        health_result = provide_runtime_dispatch_health(app.state)
        if health_result.is_error or health_result.value is None:
            response.status_code = 500
            return {
                "error": {
                    "code": "internal.unexpected",
                    "message": "Runtime dispatch health is unavailable",
                }
            }
        payload = dict(health_result.value)
        payload["worker"] = _worker_snapshot()
        return payload

    return app


__all__ = ["build_runtime_service_fastapi_app"]
