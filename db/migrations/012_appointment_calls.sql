-- AI appointment calls. The connection comes from the + menu; its API key lives in the OS keychain, never here.

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

-- Only one call at a time, enforced by the database so two requests can't both dial.
CREATE UNIQUE INDEX appointment_calls_one_active_idx ON appointment_calls (user_id) WHERE status = 'calling';
