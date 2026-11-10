"""Texts the owner on Telegram when something breaks or starts working again, if Telegram is set up."""

import logging

from src.backend import config
from src.backend.telegram_bot.telegram_api import TelegramApi, TelegramError, quiet_http_logs

logger = logging.getLogger(__name__)


def is_set_up():
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_OWNER_ID)


async def send(text, transport=None):
    """An alarm is already logged and saved, so a failed text is only logged."""
    if not is_set_up():
        return
    quiet_http_logs()
    api = TelegramApi(config.TELEGRAM_BOT_TOKEN, transport=transport)
    try:
        await api.send_message(config.TELEGRAM_OWNER_ID, text)
    except TelegramError as error:
        logger.warning("Could not text an alarm: %s", error)
    finally:
        await api.close()


def failure_text(name, problem):
    return f"⚠️ {name} isn't working: {problem}"


def recovery_text(name):
    return f"✅ {name} is working again."
