-- Word search over every chat and every saved tool action, so the model can find things from months ago.
-- Postgres fills these columns in for existing rows and keeps them up to date, so saving code doesn't change.
-- Only the first 50,000 characters are indexed, so a huge pasted message can never fail to save.

ALTER TABLE messages ADD COLUMN search_text tsvector
    GENERATED ALWAYS AS (to_tsvector('english', left(content, 50000))) STORED;
CREATE INDEX messages_search_text_idx ON messages USING GIN (search_text);

ALTER TABLE tool_activity ADD COLUMN search_text tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', label || ' ' || arguments::text || ' ' || coalesce(result, ''))
    ) STORED;
CREATE INDEX tool_activity_search_text_idx ON tool_activity USING GIN (search_text);
