-- The system prompt the owner edits in Settings. NULL means the built-in default; empty means no prompt.

ALTER TABLE user_settings ADD COLUMN system_prompt TEXT;
