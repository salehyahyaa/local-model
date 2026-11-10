"""Scores past-chat search on made-up chats with known answers: words only, meaning only, and hybrid.

    TEST_DATABASE_URL=postgresql://.../local_model_test venv/bin/python -m scripts.eval_search

Uses the test database only (it is wiped first) and runs the real bge-small model, so it's slow and not part of pytest.
Scores are printed and saved to evals/results/, where the analytics page reads them.
"""

import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

from src.backend import db, store
from src.backend.chat_memory import activity, embeddings, search
from src.backend.config import ROOT_DIR
from src.backend.models.embeddings import MODEL_NAME, client
from tests.helpers import reset_test_database

CASES_FILE = ROOT_DIR / "evals" / "chat_search" / "cases.json"
RESULTS_DIR = ROOT_DIR / "evals" / "results"
TOP = 5
LIMIT = search.DEFAULT_LIMIT
CUTOFFS = [round(0.40 + step * 0.025, 3) for step in range(13)]  # 0.40 to 0.70
MIN_EMPTY_RATE = 0.9
METHODS = (search.WORDS, search.MEANING, search.HYBRID)


def parse_time(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def load_chats(chats):
    """Puts the made-up chats in the test database. Returns {case key: (kind, id)}."""
    keys = {}
    for chat in chats:
        conversation_id = (await store.create_conversation())["id"]
        await store.update_conversation(conversation_id, {"title": chat["title"]})
        for message in chat.get("messages", []):
            message_id = await store.add_message(conversation_id, message["role"], message["text"])
            await db.pool.execute("UPDATE messages SET created_at = $2 WHERE id = $1", message_id, parse_time(message["date"]))
            keys[message["key"]] = ("message", message_id)
        for action in chat.get("actions", []):
            await activity.save(conversation_id, action["label"], action["arguments"], action["outcome"], action.get("result"))
            action_id = await db.pool.fetchval("SELECT max(id) FROM tool_activity WHERE conversation_id = $1", conversation_id)
            await db.pool.execute("UPDATE tool_activity SET created_at = $2 WHERE id = $1", action_id, parse_time(action["date"]))
            keys[action["key"]] = ("action", action_id)
    return keys


def score(question, ranking, keys):
    """recall: a right answer is in the top 5. reciprocal_rank: 1 / position of the first right answer."""
    expected = {keys[key] for key in question["expect"]}
    if not expected:
        return {"empty": not ranking}
    positions = [position for position, key in enumerate(ranking, start=1) if key in expected]
    return {
        "recall": bool(positions) and positions[0] <= TOP,
        "reciprocal_rank": 1 / positions[0] if positions else 0.0,
    }


def summarize(scores):
    """Averages per question type, plus 'answerable' over every type that has an answer."""
    by_type = {}
    for question_type, result in scores:
        by_type.setdefault(question_type, []).append(result)
    answerable = [result for question_type, result in scores if "recall" in result]
    by_type["answerable"] = answerable
    summary = {}
    for question_type, results in by_type.items():
        if not results:
            continue
        if "empty" in results[0]:
            summary[question_type] = {"questions": len(results), "empty_rate": statistics.mean(r["empty"] for r in results)}
        else:
            summary[question_type] = {
                "questions": len(results),
                "recall_at_5": statistics.mean(r["recall"] for r in results),
                "mrr": statistics.mean(r["reciprocal_rank"] for r in results),
            }
    return summary


def rankings_at(cutoff, words, similar):
    meaning = [(row["kind"], row["id"]) for row in similar if row["similarity"] >= cutoff]
    return {
        search.WORDS: search.merge(words, limit=LIMIT),
        search.MEANING: search.merge(meaning, limit=LIMIT),
        search.HYBRID: search.merge(words, meaning, limit=LIMIT),
    }


def best_cutoff(sweep):
    """The cutoff that finds the most while still returning nothing for at least 90% of questions with no answer."""
    allowed = [row for row in sweep if row["hybrid"]["nothing"]["empty_rate"] >= MIN_EMPTY_RATE] or sweep
    return max(allowed, key=lambda row: (row["hybrid"]["answerable"]["recall_at_5"], row["hybrid"]["answerable"]["mrr"], row["cutoff"]))["cutoff"]


async def evaluate(cases):
    keys = await load_chats(cases["chats"])
    questions = cases["questions"]

    started = time.perf_counter()
    embedded = await embeddings.catch_up()
    embedding_seconds = time.perf_counter() - started

    vectors = await client.embed([embeddings.QUERY_PREFIX + question["query"] for question in questions])
    candidates = []
    for question, vector in zip(questions, vectors):
        after, before = parse_time(question.get("after")), parse_time(question.get("before"))
        words = await search.find_words(question["query"], after, before)
        similar = await embeddings.find_similar(vector, after, before, search.CANDIDATES)
        candidates.append((words, similar))

    sweep = []
    for cutoff in CUTOFFS:
        per_method = {method: [] for method in METHODS}
        for question, (words, similar) in zip(questions, candidates):
            for method, ranking in rankings_at(cutoff, words, similar).items():
                per_method[method].append((question["type"], score(question, ranking, keys)))
        sweep.append({"cutoff": cutoff, **{method: summarize(per_method[method]) for method in METHODS}})

    current = next(row for row in sweep if row["cutoff"] == round(search.SIMILARITY_CUTOFF, 3))
    by_key = {value: key for key, value in keys.items()}
    misses = []
    for question, (words, similar) in zip(questions, candidates):
        ranking = rankings_at(search.SIMILARITY_CUTOFF, words, similar)[search.HYBRID]
        result = score(question, ranking, keys)
        if not result.get("recall", result.get("empty")):
            misses.append({"type": question["type"], "query": question["query"], "expected": question["expect"], "got": [by_key[key] for key in ranking[:TOP]]})

    # Real search time, including starting the model for each meaning search, as the chat tool would.
    seconds = {method: [] for method in METHODS}
    for question in questions:
        after, before = parse_time(question.get("after")), parse_time(question.get("before"))
        for method in METHODS:
            started = time.perf_counter()
            await search.find(question["query"], after, before, method=method)
            seconds[method].append(time.perf_counter() - started)

    return {
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_NAME,
        "settings": {
            "cutoff": search.SIMILARITY_CUTOFF,
            "rrfK": search.RRF_K,
            "candidates": search.CANDIDATES,
            "chunkWords": embeddings.CHUNK_WORDS,
            "chunkOverlap": embeddings.CHUNK_OVERLAP,
        },
        "items": len(keys),
        "questions": len(questions),
        "embedding": {"items": embedded, "seconds": round(embedding_seconds, 2)},
        "scores": {method: current[method] for method in METHODS},
        "latency": {
            method: {"medianMs": round(statistics.median(values) * 1000), "slowestMs": round(max(values) * 1000)}
            for method, values in seconds.items()
        },
        "cutoffSweep": sweep,
        "bestCutoff": best_cutoff(sweep),
        "hybridMisses": misses,
    }


def print_report(report):
    print(f"\n{report['model']} · {report['items']} items · {report['questions']} questions · cutoff {report['settings']['cutoff']}")
    print(f"Embedded {report['embedding']['items']} items in {report['embedding']['seconds']}s\n")
    types = list(report["scores"][search.HYBRID])
    print(f"{'type':<14}" + "".join(f"{method:>22}" for method in METHODS))
    for question_type in types:
        cells = []
        for method in METHODS:
            row = report["scores"][method].get(question_type, {})
            cells.append(f"empty {row['empty_rate']:.0%}" if "empty_rate" in row else f"R@5 {row['recall_at_5']:.0%} MRR {row['mrr']:.2f}")
        print(f"{question_type:<14}" + "".join(f"{cell:>22}" for cell in cells))
    print("\nSearch time (median / slowest):")
    for method, latency in report["latency"].items():
        print(f"  {method:<8} {latency['medianMs']} ms / {latency['slowestMs']} ms")
    print("\nCutoff sweep (hybrid): cutoff · answerable R@5 · nothing-to-find empty rate")
    for row in report["cutoffSweep"]:
        hybrid = row["hybrid"]
        print(f"  {row['cutoff']:.3f}  {hybrid['answerable']['recall_at_5']:.0%}  {hybrid['nothing']['empty_rate']:.0%}")
    print(f"\nBest cutoff on this set: {report['bestCutoff']}")
    if report["hybridMisses"]:
        print("\nHybrid misses at the current cutoff:")
        for miss in report["hybridMisses"]:
            print(f"  [{miss['type']}] {miss['query']!r}: expected {miss['expected']}, top {TOP} {miss['got']}")


async def run(database_url, cases):
    db.DATABASE_URL = database_url
    await db.connect()
    try:
        if db.pool is None:
            raise SystemExit("Could not connect to TEST_DATABASE_URL")
        return await evaluate(cases)
    finally:
        await db.disconnect()


def main():
    database_url = os.getenv("TEST_DATABASE_URL", "")
    if not database_url:
        sys.exit("Set TEST_DATABASE_URL to a throwaway Postgres database (with pgvector). It is wiped before the run.")
    reset_test_database(database_url)
    report = asyncio.run(run(database_url, json.loads(CASES_FILE.read_text())))
    print_report(report)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"search-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nSaved {path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
