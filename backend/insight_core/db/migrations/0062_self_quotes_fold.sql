-- 0062_self_quotes_fold.sql (issue 0076, the v9.15 reader review)
--
-- post_parts.subject: a quote tweet whose own words are a short reaction ("no! really?!", an emoji)
-- leads a News row by what it quotes, "<Name>: <the quoted tweet's title>" (post_fields.reaction_title);
-- its row and its page keep its own words.
--
-- post_parts.folds_into: a tweet with nothing of its own that quotes its own account's tweet (a
-- self-quoting reply, "R to @me: x.com/me/status…") is part of that tweet: when the quoted tweet is
-- stored, the post is no row of its own on any page (repo_reader.NOT_ALBUM_PIECE), as 0072 B1 already
-- leaves it out of trees, News and thread pages. The parser's stamp changed: the next start parses
-- every post again, writing the rows that changed.

ALTER TABLE post_parts ADD COLUMN IF NOT EXISTS folds_into TEXT;
ALTER TABLE post_parts ADD COLUMN IF NOT EXISTS subject TEXT;
CREATE INDEX IF NOT EXISTS post_parts_folds_into_idx ON post_parts (post_id) WHERE folds_into IS NOT NULL;
