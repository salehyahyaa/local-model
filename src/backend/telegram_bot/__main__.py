"""Runs the Telegram bot: venv/bin/python -m src.backend.telegram_bot"""

import asyncio
import logging
import sys

from src.backend import db
from src.backend.config import APP_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_TIMEOUT, TELEGRAM_OWNER_ID
from src.backend.logging_config import setup_logging
from src.backend.telegram_bot import conversations
from src.backend.telegram_bot.bot import Bot
from src.backend.telegram_bot.chat_client import ChatClient
from src.backend.telegram_bot.telegram_api import TelegramApi, quiet_http_logs

logger = logging.getLogger(__name__)

NOT_SET_UP = "Telegram isn't set up. Run: venv/bin/python -m scripts.setup_telegram"


def is_set_up(token, owner_id):
    """Without a valid owner, the bot must not start, because it couldn't tell who to answer."""
    return bool(token) and owner_id.isdigit()


async def run():
    telegram = TelegramApi(TELEGRAM_BOT_TOKEN)
    chat_client = ChatClient(APP_URL, TELEGRAM_CHAT_TIMEOUT)
    try:
        await Bot(telegram, chat_client, int(TELEGRAM_OWNER_ID), conversations).run()
    finally:
        await telegram.close()
        await chat_client.close()
        await db.disconnect()


def main():
    setup_logging("telegram_bot.log")
    quiet_http_logs()
    if not is_set_up(TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID):
        logger.error(NOT_SET_UP)
        sys.exit(1)
    logger.info("Telegram bot started")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Telegram bot stopped")


if __name__ == "__main__":
    main()
