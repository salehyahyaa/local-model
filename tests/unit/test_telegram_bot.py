import asyncio
import json
import logging

import httpx
import pytest

from src.backend.telegram_bot.__main__ import is_set_up
from src.backend.telegram_bot.bot import (
    MAX_HISTORY_MESSAGES,
    NEW_CONVERSATION_MESSAGE,
    TEXT_ONLY_MESSAGE,
    Bot,
    split_message,
)
from src.backend.telegram_bot.chat_client import APP_NOT_RUNNING, APP_STOPPED_RESPONDING, ChatClient, ChatError
from src.backend.telegram_bot.conversations import answered_messages
from src.backend.telegram_bot.telegram_api import TelegramApi, TelegramError, quiet_http_logs

TOKEN = "123456:SECRET-TOKEN"
OWNER_ID = 42
CHAT_ID = 42


def stream_body(*events):
    return "".join(json.dumps(event) + "\n" for event in events)


def text_reply(text):
    return httpx.Response(200, text=stream_body({"type": "text", "text": text}))


class FakeTelegram:
    """Answers like Telegram and records what the bot did, in order."""

    def __init__(self, updates=(), fail_send=False):
        self.updates = list(updates)
        self.fail_send = fail_send
        self.calls = []
        self.sent = []

    def handler(self, request):
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content)
        self.calls.append((method, payload))
        if method == "getUpdates":
            offset = payload.get("offset", 0)
            pending = [update for update in self.updates if update["update_id"] >= offset]
            return httpx.Response(200, json={"ok": True, "result": pending[: payload["limit"]]})
        if method == "sendMessage":
            if self.fail_send:
                return httpx.Response(500, json={"ok": False})
            self.sent.append(payload["text"])
        return httpx.Response(200, json={"ok": True, "result": True})


def make_bot(fake, chat_handler):
    telegram = TelegramApi(TOKEN, transport=httpx.MockTransport(fake.handler))
    chat_client = ChatClient("http://app.test", 5, transport=httpx.MockTransport(chat_handler))
    return Bot(telegram, chat_client, OWNER_ID)


def update(update_id=1, text="hello", sender_id=OWNER_ID, chat_type="private", **fields):
    message = {"from": {"id": sender_id}, "chat": {"id": CHAT_ID, "type": chat_type}, **fields}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


def no_model(request):
    return httpx.Response(503, json={"error": "No model is connected."})


def fail_if_called(request):
    raise AssertionError("The app should not have been called")


@pytest.fixture
def no_waiting(monkeypatch):
    async def skip(delay):
        await original_sleep(0)

    original_sleep = asyncio.sleep
    monkeypatch.setattr("src.backend.telegram_bot.bot.asyncio.sleep", skip)


@pytest.mark.parametrize(
    "incoming",
    [
        update(sender_id=999),
        update(chat_type="group"),
        update(chat_type="supergroup"),
        {"update_id": 1, "message": {"chat": {"id": CHAT_ID, "type": "private"}, "text": "no sender"}},
        {"update_id": 1},
    ],
)
def test_ignores_everyone_but_the_owner_in_private(incoming):
    fake = FakeTelegram()
    bot = make_bot(fake, fail_if_called)
    asyncio.run(bot.handle_update(incoming))
    assert fake.sent == []
    assert fake.calls == []


def test_no_model_error_reaches_the_chat_and_stays_out_of_history():
    fake = FakeTelegram()
    bot = make_bot(fake, no_model)
    asyncio.run(bot.handle_update(update()))
    assert fake.sent == ["No model is connected."]
    assert bot.history == []


def test_streamed_text_is_joined_and_kept_in_history():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"])
        body = stream_body(
            {"type": "text", "text": "Hel"},
            {"type": "tool", "label": "Searching"},
            {"type": "text", "text": "lo"},
        )
        return httpx.Response(200, text=body)

    fake = FakeTelegram()
    bot = make_bot(fake, handler)

    async def scenario():
        await bot.handle_update(update(text="first"))
        await bot.handle_update(update(text="second"))

    asyncio.run(scenario())
    assert fake.sent == ["Hello", "Hello"]
    assert seen[1] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "second"},
    ]


def test_error_event_is_shown_after_partial_text_and_not_kept():
    def handler(request):
        body = stream_body({"type": "text", "text": "Partial"}, {"type": "error", "message": "ran out of memory"})
        return httpx.Response(200, text=body)

    fake = FakeTelegram()
    bot = make_bot(fake, handler)
    asyncio.run(bot.handle_update(update()))
    assert fake.sent == ["Partial\n[Error: ran out of memory]"]
    assert bot.history == []


def test_app_not_running():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    fake = FakeTelegram()
    asyncio.run(make_bot(fake, handler).handle_update(update()))
    assert fake.sent == [APP_NOT_RUNNING]


def test_slow_app_is_not_reported_as_stopped_running():
    def handler(request):
        raise httpx.ReadTimeout("too slow")

    fake = FakeTelegram()
    asyncio.run(make_bot(fake, handler).handle_update(update()))
    assert fake.sent == [APP_STOPPED_RESPONDING]


@pytest.mark.parametrize("body", ["not json\n", '["a list"]\n', '{"type": "text"}\n'])
def test_unreadable_reply_is_reported(body):
    client = ChatClient("http://app.test", 5, transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))
    with pytest.raises(ChatError):
        asyncio.run(client.ask([{"role": "user", "content": "hi"}]))


def test_empty_reply_is_reported_and_not_kept():
    fake = FakeTelegram()
    bot = make_bot(fake, lambda request: httpx.Response(200, text=""))
    asyncio.run(bot.handle_update(update()))
    assert fake.sent == ["The model sent an empty reply."]
    assert bot.history == []


def test_history_is_capped_and_starts_with_a_user_message():
    fake = FakeTelegram()
    bot = make_bot(fake, lambda request: text_reply("ok"))

    async def scenario():
        for number in range(MAX_HISTORY_MESSAGES):
            await bot.handle_update(update(text=f"message {number}"))

    asyncio.run(scenario())
    assert len(bot.history) == MAX_HISTORY_MESSAGES
    assert bot.history[0]["role"] == "user"


def test_new_clears_history():
    fake = FakeTelegram()
    bot = make_bot(fake, lambda request: text_reply("ok"))

    async def scenario():
        await bot.handle_update(update(text="hello"))
        assert bot.history
        await bot.handle_update(update(text="/new"))

    asyncio.run(scenario())
    assert bot.history == []
    assert fake.sent[-1] == NEW_CONVERSATION_MESSAGE


def test_non_text_message_gets_text_only_reply():
    fake = FakeTelegram()
    bot = make_bot(fake, fail_if_called)
    asyncio.run(bot.handle_update(update(text=None, photo=[{"file_id": "abc"}])))
    assert fake.sent == [TEXT_ONLY_MESSAGE]


def test_long_reply_is_split_for_telegram():
    fake = FakeTelegram()
    bot = make_bot(fake, lambda request: text_reply("a" * 5000))
    asyncio.run(bot.handle_update(update()))
    assert [len(chunk) for chunk in fake.sent] == [4096, 904]


def test_split_counts_emoji_as_two_and_keeps_all_text():
    text = "😀" * 3000
    chunks = split_message(text)
    assert "".join(chunks) == text
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 4096 for chunk in chunks)


def test_update_is_confirmed_before_it_is_handled():
    order = []
    fake = FakeTelegram(updates=[update(update_id=7)])

    def chat_handler(request):
        order.append([payload.get("offset") for method, payload in fake.calls if method == "getUpdates"])
        return text_reply("ok")

    bot = make_bot(fake, chat_handler)
    offset = asyncio.run(bot.poll_once(None))
    assert offset == 8
    assert order == [[None, 8]]


def test_unexpected_error_does_not_stop_the_bot():
    fake = FakeTelegram(updates=[{"update_id": 3, "message": {"from": {"id": OWNER_ID}, "chat": {"type": "private"}}}])
    bot = make_bot(fake, fail_if_called)
    assert asyncio.run(bot.poll_once(None)) == 4


def test_polling_retries_after_a_network_drop(no_waiting):
    fake = FakeTelegram()
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise httpx.ConnectError("no network")
        return fake.handler(request)

    bot = make_bot(fake, fail_if_called)
    bot.telegram = TelegramApi(TOKEN, transport=httpx.MockTransport(handler))
    assert asyncio.run(bot.poll_once(5)) == 5
    assert len(attempts) == 3


def test_token_stays_out_of_logs_and_errors(caplog, no_waiting):
    quiet_http_logs()
    fake = FakeTelegram(fail_send=True)
    bot = make_bot(fake, no_model)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(bot.handle_update(update()))
    assert "failed" in caplog.text
    assert "SECRET-TOKEN" not in caplog.text
    assert "api.telegram.org" not in caplog.text


def test_telegram_error_text_has_no_token():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    telegram = TelegramApi(TOKEN, transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramError) as caught:
        asyncio.run(telegram.get_me())
    assert "SECRET-TOKEN" not in str(caught.value)


@pytest.mark.parametrize(
    ("token", "owner_id", "expected"),
    [("token", "42", True), ("", "42", False), ("token", "", False), ("token", "not-a-number", False)],
)
def test_bot_needs_a_token_and_a_valid_owner(token, owner_id, expected):
    assert is_set_up(token, owner_id) is expected


class FakeConversations:
    def __init__(self, history=(), broken=False):
        self.history = list(history)
        self.broken = broken
        self.questions = []
        self.replies = []
        self.ended = []

    def check(self):
        if self.broken:
            raise OSError("private message text")

    async def save_question(self, sender, telegram_message_id, text):
        self.check()
        self.questions.append((sender["id"], telegram_message_id, text))
        return 5

    async def save_reply(self, conversation_id, text):
        self.check()
        self.replies.append((conversation_id, text))

    async def end_conversation(self, telegram_user_id):
        self.check()
        self.ended.append(telegram_user_id)

    async def load_history(self, telegram_user_id, limit):
        self.check()
        return self.history


def make_saving_bot(chat_handler, conversations):
    bot = make_bot(FakeTelegram(), chat_handler)
    bot.conversations = conversations
    return bot


def test_question_and_reply_are_saved():
    saved = FakeConversations()
    bot = make_saving_bot(lambda request: text_reply("hi there"), saved)
    asyncio.run(bot.handle_update(update(message_id=9)))
    assert saved.questions == [(OWNER_ID, 9, "hello")]
    assert saved.replies == [(5, "hi there")]


def test_question_is_saved_even_when_the_model_fails():
    saved = FakeConversations()
    bot = make_saving_bot(no_model, saved)
    asyncio.run(bot.handle_update(update()))
    assert saved.questions == [(OWNER_ID, None, "hello")]
    assert saved.replies == []


def test_strangers_commands_and_non_text_are_not_saved():
    saved = FakeConversations()
    bot = make_saving_bot(fail_if_called, saved)

    async def scenario():
        await bot.handle_update(update(sender_id=999, text="private"))
        await bot.handle_update(update(text="/start"))
        await bot.handle_update(update(text=None, photo=[{"file_id": "abc"}]))

    asyncio.run(scenario())
    assert saved.questions == []


def test_new_ends_the_saved_conversation_and_does_not_restore_it():
    saved = FakeConversations(history=[{"role": "user", "content": "old"}])
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"])
        return text_reply("ok")

    bot = make_saving_bot(handler, saved)

    async def scenario():
        await bot.handle_update(update(text="/new"))
        await bot.handle_update(update(text="fresh"))

    asyncio.run(scenario())
    assert saved.ended == [OWNER_ID]
    assert seen == [[{"role": "user", "content": "fresh"}]]


def test_saved_history_is_restored_after_a_restart():
    old = [{"role": "user", "content": "before"}, {"role": "assistant", "content": "restart"}]
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"])
        return text_reply("ok")

    bot = make_saving_bot(handler, FakeConversations(history=old))
    asyncio.run(bot.handle_update(update(text="after")))
    assert seen == [[*old, {"role": "user", "content": "after"}]]


def test_database_problem_still_gets_a_reply_and_keeps_text_out_of_logs(caplog):
    fake = FakeTelegram()
    bot = make_bot(fake, lambda request: text_reply("still here"))
    bot.conversations = FakeConversations(broken=True)
    with caplog.at_level(logging.DEBUG):
        asyncio.run(bot.handle_update(update()))
    assert fake.sent == ["still here"]
    assert "OSError" in caplog.text
    assert "private message text" not in caplog.text


def test_only_answered_questions_are_sent_to_the_model_later():
    messages = [
        {"role": "user", "content": "failed"},
        {"role": "user", "content": "worked"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "failed too"},
    ]
    assert answered_messages(messages) == messages[1:3]
