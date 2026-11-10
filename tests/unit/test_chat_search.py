"""The search_past_chats tool, without a database."""

import asyncio
from datetime import datetime, timezone

import asyncpg
import pytest

from src.backend import db
from src.backend.chat_memory import search
from src.backend.integrations.toolbox import Toolbox
from src.backend.models.embeddings.client import EmbeddingError

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


# Hybrid: words and meaning together


def test_results_found_by_both_rank_first():
    words = [("message", 1), ("message", 2)]
    meaning = [("message", 3), ("message", 2)]
    assert search.merge(words, meaning, limit=3)[0] == ("message", 2)
    assert set(search.merge(words, meaning, limit=3)) == {("message", 1), ("message", 2), ("message", 3)}


def test_merge_respects_the_limit():
    assert len(search.merge([("message", n) for n in range(20)], limit=5)) == 5


@pytest.fixture
def fake_searches(monkeypatch):
    seen = {}

    async def find_words(query, after, before):
        return [("message", 1)]

    async def embed_query(query):
        return [0.0] * 384

    async def find_similar(vector, after, before, limit):
        return [
            {"kind": "message", "id": 2, "similarity": 0.8},
            {"kind": "action", "id": 5, "similarity": search.SIMILARITY_CUTOFF - 0.01},
        ]

    async def load_results(keys, query):
        seen["keys"] = keys
        return [{"kind": kind, "id": key_id} for kind, key_id in keys]

    monkeypatch.setattr(search, "find_words", find_words)
    monkeypatch.setattr(search.embeddings, "embed_query", embed_query)
    monkeypatch.setattr(search.embeddings, "find_similar", find_similar)
    monkeypatch.setattr(search, "load_results", load_results)
    return seen


def test_hybrid_uses_both_and_drops_unrelated_meaning_matches(fake_searches):
    asyncio.run(search.find("interview"))
    assert set(fake_searches["keys"]) == {("message", 1), ("message", 2)}


def test_each_method_can_be_measured_alone(fake_searches):
    asyncio.run(search.find("interview", method=search.WORDS))
    assert fake_searches["keys"] == [("message", 1)]
    asyncio.run(search.find("interview", method=search.MEANING))
    assert fake_searches["keys"] == [("message", 2)]


@pytest.mark.parametrize(
    "error", [EmbeddingError("no model"), asyncpg.UndefinedTableError("no table"), asyncpg.UndefinedObjectError("x")]
)
def test_search_falls_back_to_words_when_meaning_is_unavailable(fake_searches, monkeypatch, error):
    async def broken(query):
        raise error

    monkeypatch.setattr(search.embeddings, "embed_query", broken)
    asyncio.run(search.find("interview"))
    assert fake_searches["keys"] == [("message", 1)]
