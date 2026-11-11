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
