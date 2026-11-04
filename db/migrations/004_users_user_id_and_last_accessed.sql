-- Run once against "local-model": rename users.id -> user_id, drop username, add last_accessed_at.
-- Foreign keys in other tables follow the rename automatically.

ALTER TABLE users RENAME COLUMN id TO user_id;
ALTER TABLE users DROP COLUMN username;
ALTER TABLE users ADD COLUMN last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT now();
