-- The card the assistant pays with, Fernet-encrypted, and every purchase it made with it.

CREATE TABLE agentic_credit_cards (
    user_id             BIGINT PRIMARY KEY REFERENCES users (user_id) ON DELETE CASCADE,
    encrypted_card      TEXT NOT NULL,           -- Fernet token; the key lives in the OS keychain, never here
    last4               TEXT NOT NULL CHECK (last4 ~ '^[0-9]{4}$'),
    per_purchase_limit  NUMERIC(10, 2) NOT NULL CHECK (per_purchase_limit > 0),
    monthly_limit       NUMERIC(10, 2) NOT NULL CHECK (monthly_limit > 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agentic_purchases (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    conversation_id  BIGINT REFERENCES conversations (id) ON DELETE SET NULL,
    source           TEXT NOT NULL,              -- what paid: 'phone_call', later others
    source_id        BIGINT,                     -- e.g. the appointment_calls id
    merchant         TEXT NOT NULL,
    description      TEXT NOT NULL,
    max_amount       NUMERIC(10, 2) NOT NULL CHECK (max_amount > 0),
    amount_charged   NUMERIC(10, 2),
    card_last4       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'authorized'
        CHECK (status IN ('authorized', 'paid', 'not_charged', 'unknown')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX agentic_purchases_user_id_idx ON agentic_purchases (user_id, created_at DESC);
CREATE INDEX agentic_purchases_source_idx ON agentic_purchases (source, source_id);
