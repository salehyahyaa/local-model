-- Meaning-based search: each message and saved tool action, split into chunks, stored as numbers (embeddings)
-- made by the local bge-small model. Word search keeps working without this.
-- The vector extension must already be created by a superuser (see src/backend/models/embeddings/README.md);
-- IF NOT EXISTS makes this line a no-op then, since the owner role can't create extensions.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE search_embeddings (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id        BIGINT REFERENCES messages (id) ON DELETE CASCADE,
    tool_activity_id  BIGINT REFERENCES tool_activity (id) ON DELETE CASCADE,
    chunk             INTEGER NOT NULL DEFAULT 0,  -- which part of a long text
    model             TEXT NOT NULL,  -- a different model means the text is processed again
    embedding         vector(384) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((message_id IS NULL) <> (tool_activity_id IS NULL))
);

CREATE UNIQUE INDEX search_embeddings_message_idx ON search_embeddings (message_id, model, chunk)
    WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX search_embeddings_tool_activity_idx ON search_embeddings (tool_activity_id, model, chunk)
    WHERE tool_activity_id IS NOT NULL;
-- No vector index yet: with few rows, comparing against every one is fast and never misses a match.
