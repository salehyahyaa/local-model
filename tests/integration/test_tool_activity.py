"""Saving tool actions and searching past chats against a real database."""

import asyncio
from datetime import datetime, timezone

from src.backend import db, store
from src.backend.chat_memory import activity, search


def run_with_database(database_url, monkeypatch, scenario):
    monkeypatch.setattr(db, "DATABASE_URL", database_url)

    async def run():
        try:
            await db.connect()
            return await scenario()
        finally:
            await db.disconnect()

    return asyncio.run(run())


async def new_chat():
    return (await store.create_conversation())["id"]


def test_actions_are_saved_and_listed_oldest_first(test_database_url, monkeypatch):
    async def scenario():
        chat = await new_chat()
        await activity.save(chat, "Gmail → search_email", {"query": "x"}, activity.DONE, "found")
        await activity.save(chat, "Google Calendar → create_event", {"summary": "Fogo"}, activity.DENIED)
        return await activity.list_recent(chat)

    saved = run_with_database(test_database_url, monkeypatch, scenario)
    assert [(a["label"], a["arguments"], a["outcome"], a["result"]) for a in saved] == [
        ("Gmail → search_email", {"query": "x"}, "done", "found"),
        ("Google Calendar → create_event", {"summary": "Fogo"}, "denied", None),
    ]


def test_only_the_latest_actions_are_listed(test_database_url, monkeypatch):
    async def scenario():
        chat = await new_chat()
        for number in range(5):
            await activity.save(chat, f"Tool {number}", {}, activity.DONE)
        return await activity.list_recent(chat, limit=2)

    assert [a["label"] for a in run_with_database(test_database_url, monkeypatch, scenario)] == ["Tool 3", "Tool 4"]


def test_actions_cannot_go_into_a_chat_that_does_not_exist(test_database_url, monkeypatch):
    async def scenario():
        await activity.save(999999, "Gmail → send_email", {}, activity.DONE)
        return await db.pool.fetchval("SELECT count(*) FROM tool_activity")

    assert run_with_database(test_database_url, monkeypatch, scenario) == 0


def test_deleting_a_chat_deletes_its_actions(test_database_url, monkeypatch):
    async def scenario():
        chat = await new_chat()
        await activity.save(chat, "Gmail → send_email", {}, activity.DONE, "x" * 10000)
        assert len((await activity.list_recent(chat))[0]["result"]) == activity.MAX_SAVED_RESULT
        await store.delete_conversation(chat)
        return await db.pool.fetchval("SELECT count(*) FROM tool_activity")

    assert run_with_database(test_database_url, monkeypatch, scenario) == 0


def test_search_finds_messages_and_actions_from_every_chat(test_database_url, monkeypatch):
    async def scenario():
        old_chat = await new_chat()
        await store.add_message(old_chat, "user", "My interview update from Google is on March 3")
        await store.add_message(old_chat, "assistant", "Noted, good luck")
        other_chat = await new_chat()
        await activity.save(other_chat, "Google Calendar → create_event", {"summary": "Interview prep"}, "done")
        await store.add_message(other_chat, "system", "interview hidden instructions")
        return await search.find("interview")

    results = run_with_database(test_database_url, monkeypatch, scenario)
    assert {result["kind"] for result in results} == {"message", "action"}
    assert len(results) == 2
    assert all(result["snippet"] for result in results)


def test_search_respects_dates_and_deleted_chats(test_database_url, monkeypatch):
    async def scenario():
        chat = await new_chat()
        await store.add_message(chat, "user", "the dentist is on Friday")
        future = datetime(2100, 1, 1, tzinfo=timezone.utc)
        assert await search.find("dentist", after=future) == []
        assert len(await search.find("dentist", before=future)) == 1
        await store.delete_conversation(chat)
        return await search.find("dentist")

    assert run_with_database(test_database_url, monkeypatch, scenario) == []
