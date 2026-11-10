"""A thin wrapper around the Telegram Bot API.

The bot token is part of every Telegram URL, so it must stay out of logs and error text.
"""

import logging

import httpx

REQUEST_TIMEOUT = 15
POLL_EXTRA_TIMEOUT = 10


class TelegramError(Exception):
    """Its text never includes the URL, so it's safe to log."""


def quiet_http_logs():
    """httpx logs every request URL at INFO, and Telegram's URLs contain the bot token."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class TelegramApi:
    def __init__(self, token, transport=None):
        self.client = httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{token}/", transport=transport)

    async def call(self, method, payload, timeout=REQUEST_TIMEOUT):
        try:
            response = await self.client.post(method, json=payload, timeout=timeout)
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TelegramError(f"{method} failed: {type(error).__name__}") from None
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError(f"{method} failed: HTTP {response.status_code}")
        return body.get("result")

    async def get_me(self):
        return await self.call("getMe", {})

    async def get_updates(self, offset=None, timeout=0, limit=1):
        """Asking for an offset tells Telegram that every earlier update has been received."""
        payload = {"timeout": timeout, "limit": limit, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload, timeout=timeout + POLL_EXTRA_TIMEOUT)

    async def send_message(self, chat_id, text, reply_markup=None, html=False):
        payload = {"chat_id": chat_id, "text": text}
        if html:
            payload["parse_mode"] = "HTML"
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def answer_button(self, callback_id, text):
        return await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def edit_message(self, chat_id, message_id, text):
        """Replacing the text also removes the message's buttons."""
        return await self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text})

    async def send_typing(self, chat_id):
        return await self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    async def close(self):
        await self.client.aclose()
