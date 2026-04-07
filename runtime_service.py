from __future__ import annotations

import logging
import os
from pathlib import Path

from app.app_factory import build_services
from app.config import load_config, load_dotenv
from app.interfaces.runtime.runtime_service_app import build_runtime_service_fastapi_app


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("runtime_service")


def main() -> None:
    config_path = Path(__file__).with_name("config.json")
    config = load_config(config_path)
    env_values = load_dotenv(Path(__file__).with_name(".env"))
    runtime = build_services(
        config=config,
        env_values=env_values,
        bot_username="",
        providers_dir=Path(__file__).with_name("llm_providers"),
        plugins_dir=Path(__file__).with_name("plugins"),
        base_cwd=Path.cwd(),
    )
    app = build_runtime_service_fastapi_app(runtime)
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - dependency gap
        raise RuntimeError("Uvicorn is required to run runtime service API.") from exc

    host = str(os.getenv("RUNTIME_SERVICE_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(str(os.getenv("RUNTIME_SERVICE_PORT", "8091")).strip() or "8091")
    log_level = str(os.getenv("RUNTIME_SERVICE_LOG_LEVEL", "info")).strip() or "info"
    logger.info("starting runtime service host=%s port=%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
