"""Keeping meaning search up to date, with fake models and no database."""

import asyncio
import json

import pytest

from src.backend.chat_memory import embeddings
from src.backend.models.embeddings import DIMENSIONS, MODEL_NAME, client


def test_short_text_is_one_chunk():
    assert embeddings.chunk_text("job call with Google") == ["job call with Google"]


def test_blank_text_has_no_chunks():
    assert embeddings.chunk_text("   \n ") == []


def test_long_text_is_split_with_overlap():
    words = [f"w{number}" for number in range(600)]
    chunks = embeddings.chunk_text(" ".join(words))
    assert len(chunks) == 3
    assert all(len(chunk.split()) <= embeddings.CHUNK_WORDS for chunk in chunks)
    # The end of one chunk is repeated at the start of the next, so nothing is cut in half.
    first, second = chunks[0].split(), chunks[1].split()
    assert first[-embeddings.CHUNK_OVERLAP :] == second[: embeddings.CHUNK_OVERLAP]
    assert chunks[-1].split()[-1] == "w599"


def test_action_text_keeps_what_was_done():
    text = embeddings.action_text("Google Calendar → create_event", {"summary": "Fogo"}, '{"id": "1"}')
    assert text.startswith("Google Calendar → create_event")
    assert "Fogo" in text
    assert len(embeddings.action_text("x", {}, "y" * 10000)) == embeddings.MAX_ACTION_TEXT


def test_vectors_are_written_the_way_pgvector_reads_them():
    assert embeddings.vector_literal([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"


def test_searches_are_marked_as_searches(monkeypatch):
    seen = []

    async def embed(texts):
        seen.extend(texts)
        return [[0.0] * DIMENSIONS]

    asyncio.run(embeddings.embed_query("interview", embed))
    assert seen == [embeddings.QUERY_PREFIX + "interview"]


@pytest.fixture
def fake_store(monkeypatch):
    pending = [
        {"messageId": 1, "actionId": None, "text": "job call with Google"},
        {"messageId": None, "actionId": 7, "text": " ".join(["word"] * 300)},
        {"messageId": 2, "actionId": None, "text": "  "},
    ]
    saved = []

    async def find_pending():
        batch = list(pending)
        pending.clear()
        return batch

    async def save_vectors(rows):
        saved.extend(rows)

    monkeypatch.setattr(embeddings, "find_pending", find_pending)
    monkeypatch.setattr(embeddings, "save_vectors", save_vectors)
    return saved


def test_each_chunk_is_embedded_and_saved(fake_store):
    async def embed(texts):
        return [[float(len(text))] * DIMENSIONS for text in texts]

    assert asyncio.run(embeddings.embed_pending(embed)) == 3
    assert [(row["messageId"], row["actionId"], row["chunk"]) for row in fake_store] == [(1, None, 0), (None, 7, 0), (None, 7, 1)]
    assert fake_store[0]["vector"][0] == len("job call with Google")


def test_catching_up_stops_when_nothing_is_left(fake_store):
    calls = []

    async def embed(texts):
        calls.append(len(texts))
        return [[0.0] * DIMENSIONS for _ in texts]

    assert asyncio.run(embeddings.catch_up(embed)) == 3
    assert calls == [3]


def test_nothing_new_never_starts_the_model(monkeypatch):
    async def find_pending():
        return []

    async def embed(texts):
        raise AssertionError("The model must not start when there's nothing to embed")

    monkeypatch.setattr(embeddings, "find_pending", find_pending)
    assert asyncio.run(embeddings.catch_up(embed)) == 0


@pytest.mark.parametrize(
    "output",
    [
        b"not json",
        b'{"vectors": "x"}',
        json.dumps({"vectors": [[0.0] * DIMENSIONS]}).encode(),
        json.dumps({"vectors": [[0.0] * 3, [0.0] * 3]}).encode(),
    ],
)
def test_bad_worker_answers_are_rejected(output):
    with pytest.raises(client.EmbeddingError):
        client.read_vectors(output, 2)


@pytest.fixture
def fake_worker(monkeypatch):
    monkeypatch.setattr(client, "WORKER_MODULE", "tests.fixtures.fake_embedding_worker")


def test_client_gets_one_vector_per_text_from_the_worker(fake_worker):
    vectors = asyncio.run(client.embed(["a", "b"]))
    assert len(vectors) == 2
    assert all(len(vector) == DIMENSIONS for vector in vectors)


def test_no_texts_never_starts_a_worker(monkeypatch):
    monkeypatch.setattr(client, "WORKER_MODULE", "does.not.exist")
    assert asyncio.run(client.embed([])) == []


def test_a_crashed_worker_is_an_embedding_error(fake_worker):
    with pytest.raises(client.EmbeddingError):
        asyncio.run(client.embed(["crash"]))


def test_the_model_name_is_pinned():
    assert MODEL_NAME == "BAAI/bge-small-en-v1.5"
    assert DIMENSIONS == 384
