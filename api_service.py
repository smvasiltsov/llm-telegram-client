from __future__ import annotations

import logging
from pathlib import Path

from app.app_factory import build_read_only_api_application, build_services
from app.config import load_config, load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api_service")

API_SERVICE_HOST = "127.0.0.1"
API_SERVICE_PORT = 8080
API_SERVICE_LOG_LEVEL = "info"


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
    app = build_read_only_api_application(runtime)

    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - dependency gap
        raise RuntimeError("Uvicorn is required to run API service.") from exc

    logger.info("starting api service host=%s port=%s", API_SERVICE_HOST, API_SERVICE_PORT)
    uvicorn.run(app, host=API_SERVICE_HOST, port=API_SERVICE_PORT, log_level=API_SERVICE_LOG_LEVEL)


if __name__ == "__main__":
    main()
