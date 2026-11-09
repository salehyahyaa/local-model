-- Unfinished work found in email: a task stays open until a confirmation arrives or the owner marks it done.
-- Email bodies are never stored here.

CREATE TABLE tracked_tasks (
    id                     BIGSERIAL PRIMARY KEY,
    user_id                BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    kind                   TEXT NOT NULL DEFAULT 'other'
        CHECK (kind IN ('assessment', 'signature', 'form', 'scheduling', 'payment', 'other')),
    title                  TEXT NOT NULL,
    company                TEXT,
    company_key            TEXT,  -- normalized company, used to pair a confirmation with its task
    sender_domain          TEXT,  -- empty for free mail, where the domain says nothing about the sender
    subject_key            TEXT NOT NULL,  -- subject without Re:/Reminder:, used to spot follow-ups
    invite_message_id      TEXT NOT NULL,
    invite_date            TIMESTAMPTZ NOT NULL,
    deadline               DATE,
    status                 TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
    closed_by              TEXT CHECK (closed_by IN ('email', 'manual')),
    completion_message_id  TEXT,
    closed_at              TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, invite_message_id)
);

CREATE INDEX tracked_tasks_user_id_status_idx ON tracked_tasks (user_id, status);

-- Every email already handled, so nothing is processed or sent to a model twice.
CREATE TABLE scanned_emails (
    user_id        BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    message_id     TEXT NOT NULL,
    verdict        TEXT NOT NULL
        CHECK (verdict IN ('task', 'follow_up', 'completion', 'unmatched_completion', 'ignored', 'discarded')),
    kind           TEXT,
    company_key    TEXT,
    sender_domain  TEXT,
    email_date     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, message_id)
);

CREATE TABLE task_scan_state (
    user_id            BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    scanned_through    DATE,  -- the next scan starts here; stays put while emails wait for a model
    last_scan_at       TIMESTAMPTZ,
    needs_model_count  INTEGER NOT NULL DEFAULT 0,
    last_error         TEXT
);
