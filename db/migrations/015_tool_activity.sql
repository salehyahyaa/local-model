-- Every time the model uses a tool, and how it ended, so it can remember what it did.
-- Deleting a chat deletes its actions too.

CREATE TABLE tool_activity (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    label            TEXT NOT NULL,  -- e.g. "Google Calendar → create_event"
    arguments        JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome          TEXT NOT NULL CHECK (outcome IN ('done', 'denied', 'changed', 'failed')),
    result           TEXT,  -- what the tool answered, cut to a maximum length
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX tool_activity_conversation_id_idx ON tool_activity (conversation_id, id);
