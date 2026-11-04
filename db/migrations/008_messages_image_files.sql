-- A message can now hold several images (up to 20), so the single file name becomes a list.

ALTER TABLE messages ADD COLUMN image_files TEXT[] NOT NULL DEFAULT '{}';
UPDATE messages SET image_files = ARRAY[image_file] WHERE image_file IS NOT NULL;
ALTER TABLE messages DROP COLUMN image_file;
