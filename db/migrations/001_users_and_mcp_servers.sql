-- Database: "local-model"

CREATE TABLE users (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE mcp_servers (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
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
