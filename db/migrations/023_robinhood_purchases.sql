-- Purchases now come from the Robinhood agentic card (through its MCP server), not a card saved here.

DROP TABLE agentic_credit_cards;
DROP TABLE agentic_purchases;

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
