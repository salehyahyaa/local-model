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
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX messages_conversation_id_idx ON messages (conversation_id);

CREATE TABLE user_settings (
    user_id                 BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    theme                   TEXT NOT NULL DEFAULT 'dark' CHECK (theme IN ('light', 'dark')),
    sidebar_collapsed       BOOLEAN NOT NULL DEFAULT FALSE,
    active_conversation_id  BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    selected_model          TEXT,
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
