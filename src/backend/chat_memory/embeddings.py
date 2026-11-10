"""Keeps meaning-based search up to date: embeds new messages and tool actions with the local bge-small model.

A background loop checks every minute and only starts the model when something new is waiting, so it isn't
running otherwise. It also catches up on everything older the first time. Missed rows are picked up next time.
"""

import asyncio
import json
import logging

import asyncpg

from src.backend import config, db
from src.backend.health import jobs
from src.backend.models.embeddings import MODEL_NAME, client

logger = logging.getLogger(__name__)

JOB = "search_embeddings"
CHUNK_WORDS = 250  # bge-small reads about 512 tokens, so chunks stay well inside that
CHUNK_OVERLAP = 40
MAX_ACTION_TEXT = 4000
ITEMS_PER_BATCH = 64
MAX_BATCHES_PER_RUN = 50
NOT_SET_UP = "Meaning search isn't set up: install pgvector and run the migrations. Word search still works."
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def chunk_text(text, words=CHUNK_WORDS, overlap=CHUNK_OVERLAP):
    """Overlapping pieces, so a sentence cut at a boundary still appears whole in one of them."""
    tokens = text.split()
    if not tokens:
        return []
    step = words - overlap
    return [" ".join(tokens[start : start + words]) for start in range(0, max(len(tokens) - overlap, 1), step)]


def action_text(label, arguments, result):
    details = json.dumps(arguments, ensure_ascii=False) if arguments else ""
    return f"{label} {details} {result or ''}".strip()[:MAX_ACTION_TEXT]


def vector_literal(vector):
    """pgvector reads vectors written like [0.1,0.2]."""
    return "[" + ",".join(repr(float(number)) for number in vector) + "]"


async def find_pending(limit=ITEMS_PER_BATCH):
    """Messages and actions on this account with no embeddings from the current model, oldest first."""
    pool = db.require_pool()
    messages = await pool.fetch(
        """SELECT m.id, m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE c.user_id = $1 AND m.role IN ('user', 'assistant') AND btrim(m.content) <> ''
             AND NOT EXISTS (SELECT 1 FROM search_embeddings e WHERE e.message_id = m.id AND e.model = $2)
           ORDER BY m.id LIMIT $3""",
        db.user_id,
        MODEL_NAME,
        limit,
    )
    actions = await pool.fetch(
        """SELECT a.id, a.label, a.arguments, a.result FROM tool_activity a
           JOIN conversations c ON c.id = a.conversation_id
           WHERE c.user_id = $1
             AND NOT EXISTS (SELECT 1 FROM search_embeddings e WHERE e.tool_activity_id = a.id AND e.model = $2)
           ORDER BY a.id LIMIT $3""",
        db.user_id,
        MODEL_NAME,
        limit,
    )
    pending = [{"messageId": row["id"], "actionId": None, "text": row["content"]} for row in messages]
    pending += [
        {
            "messageId": None,
            "actionId": row["id"],
            "text": action_text(row["label"], json.loads(row["arguments"]), row["result"]),
        }
        for row in actions
    ]
    return pending


async def save_vectors(rows):
    pool = db.require_pool()
    await pool.executemany(
        """INSERT INTO search_embeddings (message_id, tool_activity_id, chunk, model, embedding)
           VALUES ($1, $2, $3, $4, $5::vector)
           ON CONFLICT DO NOTHING""",
        [(row["messageId"], row["actionId"], row["chunk"], MODEL_NAME, vector_literal(row["vector"])) for row in rows],
    )


async def embed_pending(embed=client.embed):
    """Embeds one batch. Returns how many messages and actions it covered, so 0 means everything is done."""
    pending = await find_pending()
    pieces = [
        {"messageId": item["messageId"], "actionId": item["actionId"], "chunk": number, "text": text}
        for item in pending
        for number, text in enumerate(chunk_text(item["text"]))
    ]
    if pieces:
        vectors = await embed([piece["text"] for piece in pieces])
        await save_vectors([{**piece, "vector": vector} for piece, vector in zip(pieces, vectors)])
    return len(pending)


async def catch_up(embed=client.embed):
    total = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        done = await embed_pending(embed)
        total += done
        if done == 0:
            break
    if total:
        logger.info("Embedded %d message(s) and action(s) for meaning search", total)
    return total


async def embed_query(query, embed=client.embed):
    """bge models match better when a search is marked as one."""
    return (await embed([QUERY_PREFIX + query]))[0]


async def find_similar(vector, after=None, before=None, limit=30):
    """The closest messages and actions on this account, each with its best chunk's similarity (1 is identical)."""
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT CASE WHEN e.message_id IS NOT NULL THEN 'message' ELSE 'action' END AS kind,
                  coalesce(e.message_id, e.tool_activity_id) AS id,
                  max(1 - (e.embedding <=> $1::vector)) AS similarity
           FROM search_embeddings e
           LEFT JOIN messages m ON m.id = e.message_id
           LEFT JOIN tool_activity a ON a.id = e.tool_activity_id
           JOIN conversations c ON c.id = coalesce(m.conversation_id, a.conversation_id)
           WHERE c.user_id = $2 AND e.model = $3 AND (m.id IS NULL OR m.role IN ('user', 'assistant'))
             AND ($4::timestamptz IS NULL OR coalesce(m.created_at, a.created_at) >= $4)
             AND ($5::timestamptz IS NULL OR coalesce(m.created_at, a.created_at) < $5)
           GROUP BY 1, 2
           ORDER BY similarity DESC
           LIMIT $6""",
        vector_literal(vector),
        db.user_id,
        MODEL_NAME,
        after,
        before,
        limit,
    )
    return [dict(row) for row in rows]


async def run():
    while True:
        try:
            await catch_up()
            jobs.succeeded(JOB)
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedObjectError):
            jobs.failed(JOB, NOT_SET_UP)
        except client.EmbeddingError as error:
            logger.warning("Could not embed messages: %s", error)
            jobs.failed(JOB, "The embedding model failed. See logs/app.log.")
        except Exception:
            logger.exception("Could not embed messages")
            jobs.failed(JOB, "The last run hit an error. See logs/app.log.")
        await asyncio.sleep(config.EMBEDDING_POLL_SECONDS)
