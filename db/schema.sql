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
    telegram_message_id  BIGINT  -- only on messages sent from Telegram
);

CREATE INDEX messages_conversation_id_idx ON messages (conversation_id);

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
