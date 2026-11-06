"""Answers the owner's Telegram messages through the app, one at a time. Everyone else is ignored.

Approve and Deny buttons are handled straight away, because the reply they belong to is waiting for them.
"""

import asyncio
import json
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
MAX_APPROVAL_DETAILS = 3500

CONNECTED_MESSAGE = "Connected. Send a message to talk to your model, or /new to start over."
NEW_CONVERSATION_MESSAGE = "Started a new conversation."
TEXT_ONLY_MESSAGE = "Only text messages work for now."
TAP_A_BUTTON_MESSAGE = "Tap Approve or Deny above, or type a change. I'll get to this message right after."
APPROVE_PREFIX = "approve:"
DENY_PREFIX = "deny:"
NO_LONGER_WAITING = "This request is no longer waiting."


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


def describe_approval(event):
    """Shows exactly what would happen, as plain text, so the model's words can't change how the message looks."""
    details = event.get("details") or {}
    lines = [
        f"{name}: {value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}"
        for name, value in details.items()
    ]
    text = "\n".join(lines)
    if len(text) > MAX_APPROVAL_DETAILS:
        text = f"{text[:MAX_APPROVAL_DETAILS]}\n[The rest is cut off here]"
    return f"Approve this?\n{event.get('label', 'An action')}\n\n{text}".strip()


def approval_buttons(approval_id):
    return {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"{APPROVE_PREFIX}{approval_id}"},
                {"text": "Deny", "callback_data": f"{DENY_PREFIX}{approval_id}"},
            ]
        ]
    }


def read_button(data):
    """Returns (approval id, approved), or None for anything this bot didn't send."""
    if not isinstance(data, str):
        return None
    if data.startswith(APPROVE_PREFIX):
        return data[len(APPROVE_PREFIX) :], True
    if data.startswith(DENY_PREFIX):
        return data[len(DENY_PREFIX) :], False
    return None


class Bot:
    def __init__(self, telegram, chat_client, owner_id, conversations=None):
        self.telegram = telegram
        self.chat_client = chat_client
        self.owner_id = owner_id
        self.conversations = conversations
        self.history = []
        self.history_restored = False
        self.latest_work = None
        self.waiting_approvals = set()
        self.follow_ups = []

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
            if "callback_query" in update:
                await self.handle_safely(self.handle_button(update["callback_query"]))
            elif self.is_from_owner(update.get("message")):
                await self.queue_message(update)
        return offset

    async def queue_message(self, update):
        """Polling carries on while a reply runs, so a button tap or follow-up can reach the reply waiting for it."""
        if self.waiting_approvals:
            message = update["message"]
            text = message.get("text")
            if text and text.strip() and not text.startswith("/"):
                if await self.send_follow_up(message):
                    return
            else:
                await self.send(message["chat"]["id"], TAP_A_BUTTON_MESSAGE)
        self.latest_work = asyncio.create_task(self.handle_after(self.latest_work, update))

    async def send_follow_up(self, message):
        """Returns False if the request stopped waiting, so the message can be answered normally instead."""
        approval_id = next(iter(self.waiting_approvals))
        self.waiting_approvals.discard(approval_id)
        try:
            delivered = await self.chat_client.send_follow_up(approval_id, message["text"])
        except ChatError:
            return False
        if delivered:
            self.follow_ups.append({"role": "user", "content": message["text"]})
            await self.save(lambda log: log.save_question(message["from"], message.get("message_id"), message["text"]))
        return delivered

    async def handle_after(self, earlier_work, update):
        if earlier_work is not None:
            await earlier_work
        await self.handle_safely(self.handle_update(update))

    async def handle_safely(self, work):
        try:
            await work
        except Exception as error:
            # Only the type: an unexpected error's text could include a Telegram URL.
            logger.error("Could not handle a Telegram update: %s", type(error).__name__)

    async def handle_button(self, callback):
        """Only the owner's taps count, and each request can only be answered once."""
        if (callback.get("from") or {}).get("id") != self.owner_id:
            return
        button = read_button(callback.get("data"))
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        if button is None or chat.get("type") != "private":
            return

        approval_id, approved = button
        try:
            answered = await self.chat_client.answer_approval(approval_id, approved)
        except ChatError as error:
            await self.telegram.answer_button(callback["id"], str(error))
            return
        self.waiting_approvals.discard(approval_id)
        result = ("Approved" if approved else "Denied") if answered else NO_LONGER_WAITING
        await self.telegram.answer_button(callback["id"], result)
        await self.telegram.edit_message(chat["id"], message["message_id"], f"{message.get('text', '')}\n\n{result}")

    async def ask_for_approval(self, chat_id, event):
        self.waiting_approvals.add(event["id"])
        await self.retry_sending(
            lambda: self.telegram.send_message(chat_id, describe_approval(event), approval_buttons(event["id"]))
        )

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
        self.follow_ups = []
        typing =asyncio.create_task(self.keep_typing(chat_id))
        try:
            reply = await self.chat_client.ask(
                [*self.history, question],
                conversation_id,
                lambda event: self.ask_for_approval(chat_id, event),
            )
        except ChatError as error:
            # Failed exchanges stay out of the history, so the model never sees them later.
            await self.send(chat_id, str(error))
            return
        finally:
            self.waiting_approvals.clear()
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)

        answered = [question, *self.follow_ups, {"role": "assistant", "content": reply}]
        self.history = [*self.history, *answered][-MAX_HISTORY_MESSAGES:]
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
        await self.retry_sending(lambda: self.telegram.send_message(chat_id, chunk))

    async def retry_sending(self, sending):
        delay = 1
        for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
            try:
                await sending()
                return
            except TelegramError as error:
                logger.warning("%s (attempt %s of %s)", error, attempt, MAX_SEND_ATTEMPTS)
                if attempt < MAX_SEND_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= 2
        logger.error("Gave up sending a Telegram message")
