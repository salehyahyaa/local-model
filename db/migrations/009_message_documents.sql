-- Run once against "local-model" (adds documents attached to messages; PDFs only for now).
-- The file itself is stored on disk under UPLOAD_DIR as <storage_key>; only its details live here.

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
