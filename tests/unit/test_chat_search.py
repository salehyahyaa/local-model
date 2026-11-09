"""The search_past_chats tool, without a database."""

import asyncio
from datetime import datetime, timezone

import pytest

from src.backend import db
from src.backend.chat_memory import search
from src.backend.integrations.toolbox import Toolbox

WHEN = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)


def test_tool_is_only_offered_with_a_database(monkeypatch):
    monkeypatch.setattr(db, "pool", None)
    box = Toolbox()
    search.register(box)
    assert box.definitions == []


def test_tool_never_needs_approval(monkeypatch):
    monkeypatch.setattr(db, "pool", object())
    box = Toolbox()
    search.register(box)
    name = box.definitions[0]["function"]["name"]
    assert box.needs_approval(name) is False
    assert box.label_for(name) == search.LABEL


def test_search_reads_words_dates_and_limit():
    found = search.read_search({"query": "  interview ", "after": "2026-08-01", "before": "2026-09-01", "limit": 99})
    assert found["query"] == "interview"
    assert found["after"].date().isoformat() == "2026-08-01"
    assert found["after"].tzinfo is not None
    assert found["limit"] == search.MAX_LIMIT


@pytest.mark.parametrize("arguments", [{}, {"query": "  "}, {"query": 5}, {"query": "x", "after": "August"}])
def test_unclear_searches_are_explained_to_the_model(arguments):
    with pytest.raises(search.SearchError):
        search.read_search(arguments)


def test_long_queries_are_cut():
    assert len(search.read_search({"query": "a" * 1000})["query"]) == search.MAX_QUERY_LENGTH


def test_results_show_date_chat_and_who_said_it():
    message = {"kind": "message", "created_at": WHEN, "title": "Jobs", "role": "user", "snippet": "my **interview**"}
    action = {
        "kind": "action",
        "created_at": WHEN,
        "title": "Plans",
        "label": "Google Calendar → create_event",
        "outcome": "done",
        "snippet": "Fogo",
    }
    text = search.format_results("interview", [message, action])
    assert "Found 2 result(s)" in text
    assert 'chat "Jobs" · the owner said: my **interview**' in text
    assert "your tool Google Calendar → create_event (done): Fogo" in text
    assert "2026" in text


def test_no_results_tells_the_model_to_try_other_words():
    assert "Try other words" in search.format_results("interview", [])


def test_tool_passes_the_search_to_the_database_and_formats_it(monkeypatch):
    seen = {}

    async def find(query, after, before, limit):
        seen.update(query=query, limit=limit)
        return []

    monkeypatch.setattr(search, "find", find)
    answer = asyncio.run(search.search_past_chats({"query": "job call"}))
    assert seen == {"query": "job call", "limit": search.DEFAULT_LIMIT}
    assert answer.startswith("Nothing found")


def test_tool_errors_reach_the_model_as_errors(monkeypatch):
    async def find(**kwargs):
        raise db.DatabaseUnavailableError()

    monkeypatch.setattr(search, "find", find)
    assert asyncio.run(search.search_past_chats({"query": "x"})).startswith("Error:")
    assert asyncio.run(search.search_past_chats({})).startswith("Error:")
