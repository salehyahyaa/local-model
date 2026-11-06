"""Texts the owner a call's result on Telegram."""

import logging

from src.backend import config
from src.backend.telegram_bot.telegram_api import TelegramApi, TelegramError, quiet_http_logs

logger = logging.getLogger(__name__)


async def send_result(message, transport=None):
    """The result is already saved, so a failed text is only logged."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_OWNER_ID:
        logger.info("Telegram isn't set up, so a call result wasn't texted")
        return
    quiet_http_logs()
    api = TelegramApi(config.TELEGRAM_BOT_TOKEN, transport=transport)
    try:
        await api.send_message(config.TELEGRAM_OWNER_ID, message)
    except TelegramError as error:
        logger.warning("Could not text a call result: %s", error)
    finally:
        await api.close()
