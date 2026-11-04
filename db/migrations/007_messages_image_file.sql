-- Name of the image file attached to a message, stored under data/images. NULL for text-only messages.

ALTER TABLE messages ADD COLUMN image_file TEXT;
