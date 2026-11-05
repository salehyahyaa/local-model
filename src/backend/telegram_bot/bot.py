"""Reads Telegram messages one at a time and answers the owner through the app. Everyone else is ignored."""

import asyncio
import logging

from src.backend.telegram_bot.chat_client import ChatError
from src.backend.telegram_bot.telegram_api import TelegramError

logger = logging.getLogger(__name__)

POLL_SECONDS = 30
MAX_RETRY_DELAY = 60
MAX_SEND_ATTEMPTS = 5
TYPING_INTERVAL = 4
MAX_HISTORY_MESSAGES = 20
MAX_MESSAGE_LENGTH = 4096

CONNECTED_MESSAGE = "Connected. Send a message to talk to your model, or /new to start over."
NEW_CONVERSATION_MESSAGE = "Started a new conversation."
TEXT_ONLY_MESSAGE = "Only text messages work for now."


def split_message(text, limit=MAX_MESSAGE_LENGTH):
    """Telegram can count an emoji as two characters, so each one counts as two here."""
    chunks = []
    current = []
    size = 0
    for character in text:
        width = 2 if ord(character) > 0xFFFF else 1
        if size + width > limit:
            chunks.append("".join(current))
            current = []
            size = 0
        current.append(character)
        size += width
    chunks.append("".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


class Bot:
    def __init__(self, telegram, chat_client, owner_id, conversations=None):
        self.telegram = telegram
        self.chat_client = chat_client
        self.owner_id = owner_id
        self.conversations = conversations
        self.history = []
        self.history_restored = False

    async def run(self):
        offset = None
        while True:
            offset = await self.poll_once(offset)

    async def poll_once(self, offset):
        updates = await self.retry_until_done(
            lambda: self.telegram.get_updates(offset=offset, timeout=POLL_SECONDS)
        )
        for update in updates:
            offset = update["update_id"] + 1
            # Confirmed before it's handled, so a restart can never run the same message twice.
            await self.retry_until_done(lambda: self.telegram.get_updates(offset=offset))
            try:
                await self.handle_update(update)
            except Exception as error:
                # Only the type: an unexpected error's text could include a Telegram URL.
                logger.error("Could not handle a Telegram update: %s", type(error).__name__)
        return offset

    async def retry_until_done(self, call):
        delay = 1
        while True:
            try:
                return await call()
            except TelegramError as error:
                logger.warning("%s. Trying again in %ss", error, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)

    async def handle_update(self, update):
        message = update.get("message")
        if not self.is_from_owner(message):
            return

        chat_id = message["chat"]["id"]
        text = message.get("text")
        if text is None:
            await self.send(chat_id, TEXT_ONLY_MESSAGE)
        elif text.strip() == "/start":
            await self.send(chat_id, CONNECTED_MESSAGE)
        elif text.strip() == "/new":
            self.history = []
            self.history_restored = True
            await self.save(lambda log: log.end_conversation(self.owner_id))
            await self.send(chat_id, NEW_CONVERSATION_MESSAGE)
        else:
            await self.answer(message)

    def is_from_owner(self, message):
        if not isinstance(message, dict):
            return False
        sender_id = (message.get("from") or {}).get("id")
        chat_type = (message.get("chat") or {}).get("type")
        return chat_type == "private" and sender_id == self.owner_id

    async def save(self, action):
        """A database problem must never stop the owner getting a reply. Message text stays out of the log."""
        if self.conversations is None:
            return None
        try:
            return await action(self.conversations)
        except Exception as error:
            logger.error("Could not use the saved Telegram conversations: %s", type(error).__name__)
            return None

    async def restore_history(self):
        if self.history_restored:
            return
        restored = await self.save(lambda log: log.load_history(self.owner_id, MAX_HISTORY_MESSAGES))
        if restored is not None:
            self.history = restored
            self.history_restored = True

    async def answer(self, message):
        chat_id = message["chat"]["id"]
        text = message["text"]
        await self.restore_history()
        # Saved before the model runs, so the message is kept even if the reply fails.
        conversation_id = await self.save(
            lambda log: log.save_question(message["from"], message.get("message_id"), text)
        )

        question = {"role": "user", "content": text}
        typing = asyncio.create_task(self.keep_typing(chat_id))
        try:
            reply = await self.chat_client.ask([*self.history, question])
        except ChatError as error:
            # Failed exchanges stay out of the history, so the model never sees them later.
            await self.send(chat_id, str(error))
            return
        finally:
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)

        self.history = [*self.history, question, {"role": "assistant", "content": reply}][-MAX_HISTORY_MESSAGES:]
        if conversation_id is not None:
            await self.save(lambda log: log.save_reply(conversation_id, reply))
        await self.send(chat_id, reply)

    async def keep_typing(self, chat_id):
        """Telegram hides "typing…" after about five seconds, so it needs repeating during a long reply."""
        while True:
            try:
                await self.telegram.send_typing(chat_id)
            except TelegramError as error:
                logger.warning("%s", error)
            await asyncio.sleep(TYPING_INTERVAL)

    async def send(self, chat_id, text):
        for chunk in split_message(text):
            await self.send_chunk(chat_id, chunk)

    async def send_chunk(self, chat_id, chunk):
        delay = 1
        for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
            try:
                await self.telegram.send_message(chat_id, chunk)
                return
            except TelegramError as error:
                logger.warning("%s (attempt %s of %s)", error, attempt, MAX_SEND_ATTEMPTS)
                if attempt < MAX_SEND_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= 2
        logger.error("Gave up sending a Telegram message")
