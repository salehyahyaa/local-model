-- Saves Telegram bot chats. They use the normal conversations and messages tables; these tables add the Telegram details.

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

ALTER TABLE messages ADD COLUMN telegram_message_id BIGINT;  -- only on messages sent from Telegram
