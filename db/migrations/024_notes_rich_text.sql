-- Notes now keep bold and italic, so their text is stored as simple HTML.
-- Turns existing plain-text notes into the same words as HTML.

UPDATE notes
SET text = replace(replace(replace(replace(text, '&', '&amp;'), '<', '&lt;'), '>', '&gt;'), E'\n', '<br>');
