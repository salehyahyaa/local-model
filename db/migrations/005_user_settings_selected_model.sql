-- Remembers which model the user picked in the model menu. NULL means the configured default.

ALTER TABLE user_settings ADD COLUMN selected_model TEXT;
