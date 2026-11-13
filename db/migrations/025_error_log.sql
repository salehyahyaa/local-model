-- Every error the app runs into, kept so the model can learn from its own mistakes later.
-- Deleting a chat keeps its errors, just without the link to the chat.

CREATE TABLE error_log (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    conversation_id  BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    source           TEXT NOT NULL,  -- where it happened: 'chat', 'telegram'
    kind             TEXT NOT NULL,  -- e.g. 'ModelError', 'ConnectTimeout', 'HTTP 500'
    message          TEXT NOT NULL,  -- what went wrong, cut to a maximum length
    attempted        TEXT,           -- what was being done, e.g. 'answering a Telegram message'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX error_log_user_id_idx ON error_log (user_id, created_at DESC);
