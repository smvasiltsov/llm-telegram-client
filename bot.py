from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram import BotCommand, Update
from telegram import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeChat, BotCommandScopeDefault

from app.app_factory import build_application, build_services
from app.config import load_config, load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")


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
    application = build_application(config, runtime)
    me = await application.bot.get_me()
    runtime.bot_username = me.username or ""
    if runtime.tools_bash_enabled and not runtime.tools_bash_password:
        logger.warning("BASH_DANGEROUS_PASSWORD is empty; privileged bash commands will be blocked")
    runtime.plugin_server.start()

    try:
        await application.initialize()
        owner_commands = [
            BotCommand("groups", "Список групп и выбор"),
            BotCommand("tools", "Список инструментов"),
        ]
        if runtime.tools_bash_enabled:
            owner_commands.append(BotCommand("bash", "Выполнить bash команду"))
        await application.bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=config.owner_user_id))
        await application.bot.set_my_commands([], scope=BotCommandScopeAllPrivateChats())
        await application.bot.set_my_commands([], scope=BotCommandScopeAllGroupChats())
        await application.bot.set_my_commands([], scope=BotCommandScopeDefault())
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Release bot started as @%s", runtime.bot_username)
        await asyncio.Event().wait()
    finally:
        runtime.plugin_server.stop()
        for client in runtime.llm_clients.values():
            await client.aclose()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
