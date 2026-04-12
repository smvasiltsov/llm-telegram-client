from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.app_factory import build_services
from app.core.contracts.interface_io import CorePort, InboundEvent, OutboundAction
from app.config import load_config, load_dotenv
from app.interfaces.runtime import InterfaceRuntimeConfig, InterfaceRuntimeRunner


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("telegram_service")


class _NoopCorePort(CorePort):
    async def handle_event(self, event: InboundEvent) -> list[OutboundAction]:
        return []


async def main() -> None:
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
    interface_runner = InterfaceRuntimeRunner(
        config=InterfaceRuntimeConfig(
            active_interface="telegram",
            modules_dir=runtime.interface_modules_dir,
            runtime_mode=runtime.interface_runtime_mode,
        ),
        runtime=runtime,
        core_port=_NoopCorePort(),
        adapter_config={
            "telegram_bot_token": config.telegram_bot_token,
            "owner_user_id": config.owner_user_id,
            "api_base_url": config.telegram_api_base_url,
            "api_timeout_sec": config.telegram_api_timeout_sec,
            "thin_client_enabled": config.telegram_thin_client_enabled,
        },
    )
    runtime.plugin_server.start()

    try:
        logger.info(
            "starting telegram service mode=%s thin=%s api_base_url=%s",
            runtime.interface_runtime_mode,
            config.telegram_thin_client_enabled,
            config.telegram_api_base_url,
        )
        await interface_runner.start()
        await asyncio.Event().wait()
    finally:
        runtime.plugin_server.stop()
        for client in runtime.llm_clients.values():
            await client.aclose()
        await interface_runner.stop()


if __name__ == "__main__":
    asyncio.run(main())
