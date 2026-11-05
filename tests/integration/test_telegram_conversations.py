"""Saving Telegram chats against a real database."""

import asyncio

from src.backend import db, store
from src.backend.telegram_bot import conversations

OWNER = {"id": 7000000001, "first_name": "Sam", "last_name": "Lee", "username": "samlee"}


def run_with_database(database_url, monkeypatch, scenario):
    monkeypatch.setattr(db, "DATABASE_URL", database_url)

    async def run():
        try:
            return await scenario()
        finally:
            await db.disconnect()

    return asyncio.run(run())


def test_saves_details_messages_and_restores_history(test_database_url, monkeypatch):
    async def scenario():
        first = await conversations.save_question(OWNER, 11, "Hello there")
        await conversations.save_reply(first, "Hi")
        second = await conversations.save_question({**OWNER, "first_name": "Samuel"}, 12, "No reply to this")
        assert second == first

        user = await db.pool.fetchrow("SELECT * FROM telegram_users")
        assert user["telegram_user_id"] == OWNER["id"]
        assert user["user_id"] == db.user_id
        assert (user["first_name"], user["last_name"], user["username"]) == ("Samuel", "Lee", "samlee")

        rows = await db.pool.fetch(
            "SELECT role, content, telegram_message_id FROM messages WHERE conversation_id = $1 ORDER BY id", first
        )
        assert [tuple(row) for row in rows] == [
            ("user", "Hello there", 11),
            ("assistant", "Hi", None),
            ("user", "No reply to this", 12),
        ]
        assert await conversations.load_history(OWNER["id"], 20) == [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi"},
        ]

        state = await store.get_state()
        assert [conversation["title"] for conversation in state["conversations"]] == ["Telegram: Hello there"]

    run_with_database(test_database_url, monkeypatch, scenario)


def test_new_starts_another_conversation(test_database_url, monkeypatch):
    async def scenario():
        first = await conversations.save_question(OWNER, 1, "first")
        await conversations.end_conversation(OWNER["id"])
        assert await conversations.load_history(OWNER["id"], 20) == []
        second = await conversations.save_question(OWNER, 2, "second")
        assert second != first

    run_with_database(test_database_url, monkeypatch, scenario)


def test_deleting_a_conversation_in_the_app_starts_a_new_one(test_database_url, monkeypatch):
    async def scenario():
        first = await conversations.save_question(OWNER, 1, "first")
        assert await store.delete_conversation(first)
        assert await db.pool.fetchval("SELECT count(*) FROM telegram_conversations") == 0
        assert await conversations.save_question(OWNER, 2, "second") != first

    run_with_database(test_database_url, monkeypatch, scenario)
