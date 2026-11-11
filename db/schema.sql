-- Database: "local-model"

CREATE TABLE users (
    user_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed_at  TIMESTAMPTZ NOT NULL DEFAULT now()  -- updated by the backend on activity
);

CREATE TABLE mcp_servers (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    transport   TEXT NOT NULL CHECK (transport IN ('http', 'stdio')),
    url         TEXT,                                -- http servers
    headers     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- http servers (e.g. auth header)
    command     TEXT,                                -- stdio servers
    args        TEXT[] NOT NULL DEFAULT '{}',        -- stdio servers
    env         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- stdio servers (e.g. API keys)
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name),
    CHECK (
        (transport = 'http'  AND url IS NOT NULL AND command IS NULL)
     OR (transport = 'stdio' AND command IS NOT NULL AND url IS NULL)
    )
);

CREATE INDEX mcp_servers_user_id_idx ON mcp_servers (user_id);

CREATE TABLE conversations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    title        TEXT NOT NULL DEFAULT 'New chat',
    is_pinned    BOOLEAN NOT NULL DEFAULT FALSE,
    is_archived  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX conversations_user_id_idx ON conversations (user_id);

CREATE TABLE messages (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content          TEXT NOT NULL,
    model            TEXT,
    image_files      TEXT[] NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    telegram_message_id  BIGINT,  -- only on messages sent from Telegram
    search_text      tsvector GENERATED ALWAYS AS (to_tsvector('english', left(content, 50000))) STORED
);

CREATE INDEX messages_conversation_id_idx ON messages (conversation_id);
CREATE INDEX messages_search_text_idx ON messages USING GIN (search_text);

CREATE TABLE user_settings (
    user_id                 BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    theme                   TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('light', 'dark')),
    sidebar_collapsed       BOOLEAN NOT NULL DEFAULT FALSE,
    active_conversation_id  BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    selected_model          TEXT,
    system_prompt           TEXT,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_integrations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL,
    method       TEXT NOT NULL CHECK (method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')),
    url          TEXT NOT NULL,
    parameters   JSONB NOT NULL DEFAULT '[]'::jsonb,
    headers      JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

CREATE INDEX api_integrations_user_id_idx ON api_integrations (user_id);

-- Created and maintained by src/backend/migrations.py
CREATE TABLE schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Documents attached to messages (PDFs only for now). Files live on disk under UPLOAD_DIR as <storage_key>.
CREATE TABLE message_documents (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id    BIGINT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    file_name     TEXT NOT NULL CHECK (length(file_name) BETWEEN 1 AND 255),
    content_type  TEXT NOT NULL CHECK (content_type IN ('application/pdf')),
    size_bytes    BIGINT NOT NULL CHECK (size_bytes > 0),
    sha256        TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    storage_key   TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX message_documents_message_id_idx ON message_documents (message_id);

-- Telegram bot chats use the normal conversations and messages tables; these tables add the Telegram details.
CREATE TABLE telegram_users (
    telegram_user_id  BIGINT PRIMARY KEY,  -- the ID Telegram gives the account
    user_id           BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    first_name        TEXT,
    last_name         TEXT,
    username          TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX telegram_users_user_id_idx ON telegram_users (user_id);

CREATE TABLE telegram_conversations (
    conversation_id   BIGINT PRIMARY KEY REFERENCES conversations (id) ON DELETE CASCADE,
    telegram_user_id  BIGINT NOT NULL REFERENCES telegram_users (telegram_user_id) ON DELETE CASCADE,
    ended_at          TIMESTAMPTZ,  -- set by /new; the next message starts another conversation
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX telegram_conversations_telegram_user_id_idx ON telegram_conversations (telegram_user_id);

CREATE TABLE phone_call_connections (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL UNIQUE REFERENCES users (user_id) ON DELETE CASCADE,
    owner_name        TEXT NOT NULL,  -- who the agent says it's calling for
    agent_id          TEXT NOT NULL,  -- ElevenLabs agent
    phone_number_id   TEXT NOT NULL,  -- the Twilio number, as imported into ElevenLabs
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE appointment_calls (
    id                          BIGSERIAL PRIMARY KEY,
    user_id                     BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    conversation_id             BIGINT REFERENCES conversations (id) ON DELETE SET NULL,  -- where the result is posted
    contact_name                TEXT NOT NULL,
    phone_number                TEXT NOT NULL,
    reason                      TEXT NOT NULL,
    allowed_slots               JSONB NOT NULL,
    timezone                    TEXT NOT NULL,
    deadline                    TIMESTAMPTZ NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'calling'
        CHECK (status IN ('calling', 'booked', 'needs_review', 'not_booked', 'failed', 'unknown')),
    elevenlabs_conversation_id  TEXT,
    twilio_call_sid             TEXT,
    booked_time                 TIMESTAMPTZ,
    result_message              TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX appointment_calls_user_id_created_at_idx ON appointment_calls (user_id, created_at DESC);

CREATE TABLE tracked_tasks (
    id                     BIGSERIAL PRIMARY KEY,
    user_id                BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    title                  TEXT NOT NULL,
    company                TEXT,
    request_message_id     TEXT NOT NULL,
    request_date           TIMESTAMPTZ NOT NULL,
    deadline               DATE,
    status                 TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
    closed_by              TEXT CHECK (closed_by IN ('email', 'manual')),
    completion_message_id  TEXT,
    closed_at              TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, request_message_id)
);

CREATE INDEX tracked_tasks_user_id_status_idx ON tracked_tasks (user_id, status);

-- Every email already handled, so nothing is processed or sent to a model twice.
CREATE TABLE scanned_emails (
    user_id     BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    message_id  TEXT NOT NULL,
    verdict     TEXT NOT NULL CHECK (verdict IN ('task', 'same_task', 'completion', 'neither', 'discarded')),
    email_date  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, message_id)
);

CREATE TABLE task_scan_state (
    user_id          BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    scanned_through  DATE,  -- the next scan starts here; stays put until a whole week is judged
    last_scan_at     TIMESTAMPTZ,
    waiting_count    INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT
);

-- Every time the model uses a tool, and how it ended, so it can remember what it did.
CREATE TABLE tool_activity (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    label            TEXT NOT NULL,  -- e.g. "Google Calendar → create_event"
    arguments        JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome          TEXT NOT NULL CHECK (outcome IN ('done', 'denied', 'changed', 'failed')),
    result           TEXT,  -- what the tool answered, cut to a maximum length
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_text      tsvector GENERATED ALWAYS AS (
        to_tsvector('english', label || ' ' || arguments::text || ' ' || coalesce(result, ''))
    ) STORED
);

CREATE INDEX tool_activity_conversation_id_idx ON tool_activity (conversation_id, id);
CREATE INDEX tool_activity_search_text_idx ON tool_activity USING GIN (search_text);

-- Health alarms: one row each time a check starts failing, closed when it works again.
CREATE TABLE alarms (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    check_key    TEXT NOT NULL,  -- e.g. "database", "job:task_scan", "integration:mcp:3"
    name         TEXT NOT NULL,  -- what failed, as the owner sees it
    problem      TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX alarms_one_active_per_check_idx ON alarms (user_id, check_key) WHERE resolved_at IS NULL;
CREATE INDEX alarms_user_id_started_at_idx ON alarms (user_id, started_at DESC);

-- Meaning-based search: messages and tool actions as numbers from the local bge-small model.
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

-- Sticky notes from the Notes tab.
CREATE TABLE notes (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    text        TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT 'yellow',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX notes_user_id_idx ON notes (user_id, id DESC);

-- Tasks the model carries out at a set time, created from chat or the Scheduled page.
CREATE TABLE scheduled_tasks (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    title                 TEXT NOT NULL,
    instruction           TEXT NOT NULL,
    repeat                TEXT NOT NULL DEFAULT 'once',
    next_run_at           TIMESTAMPTZ,
    is_active             BOOLEAN NOT NULL DEFAULT true,
    last_run_at           TIMESTAMPTZ,
    last_status           TEXT,
    last_conversation_id  BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX scheduled_tasks_due_idx ON scheduled_tasks (next_run_at) WHERE is_active;
CREATE INDEX scheduled_tasks_user_id_idx ON scheduled_tasks (user_id, id DESC);

CREATE TABLE agentic_purchases (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,                  -- 'robinhood'
    purchase_id      TEXT NOT NULL,                  -- the provider's own transaction id
    merchant         TEXT NOT NULL,
    total            NUMERIC(12, 2) NOT NULL,        -- US dollars
    status           TEXT NOT NULL,                  -- as the provider says it: POSTED, PENDING, DECLINED, ...
    decline_reason   TEXT,                           -- e.g. AGENT_PENDING, AGENT_REJECTED, TRANSACTION_ERROR
    approval_status  TEXT,                           -- the owner's answer to an approval request: AUTHORIZED, ...
    purchased_at     TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, provider, purchase_id)
);

CREATE INDEX agentic_purchases_user_id_idx ON agentic_purchases (user_id, purchased_at DESC);
