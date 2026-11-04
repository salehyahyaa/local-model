-- Records which model option each message was sent with. NULL for messages saved before this existed.

ALTER TABLE messages ADD COLUMN model TEXT;
