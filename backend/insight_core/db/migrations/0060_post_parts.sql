-- 0060_post_parts.sql (issue 0076: a post is read once, when it is saved)
--
-- post_parts: one row per post, what the one parser (utils/post_parser.py) reads of its raw title,
-- text and HTML: the title every place shows and where it came from, a row's lead, the post page's
-- text and HTML as cut points into the raw columns (utils/post_parts.Body: the kept spans, read after
-- decoding HTML codes, joined by line breaks; a copy only where no cut says it), the quote, the
-- footer's counts and link, the reply, Reddit's poster, the words, and where a rule guessed.
-- Written at save and by the parse's catch-up (repo_post_parts: the posts with no row, and every post
-- again when the parser's stamp changes, writing only the rows whose digest changed). The raw columns
-- never change for it; a change to them drops the row (the trigger below), so no row is ever read
-- against another body than it was cut from. The first start after it parses every post, in batches,
-- in a process of its own (DEPLOYMENT.md).

CREATE TABLE IF NOT EXISTS post_parts (
    post_id UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    title_from TEXT NOT NULL,
    lead TEXT NOT NULL,
    text_cut INTEGER[],
    text_decode_entities BOOLEAN NOT NULL DEFAULT FALSE,
    text_cut_leaves_break BOOLEAN NOT NULL DEFAULT FALSE,
    text_copy TEXT,
    html_cut INTEGER[],
    html_decode_entities BOOLEAN NOT NULL DEFAULT FALSE,
    html_cut_leaves_break BOOLEAN NOT NULL DEFAULT FALSE,
    html_copy TEXT,
    quoted TEXT,
    quote_only TEXT,
    folded JSONB,
    counts JSONB,
    link_target TEXT,
    link_kind TEXT,
    reply_to TEXT,
    author TEXT,
    words INTEGER NOT NULL DEFAULT 0,
    quoted_words JSONB,
    warnings TEXT[],
    parse_stamp TEXT NOT NULL,
    parsed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    digest TEXT NOT NULL
);

CREATE OR REPLACE FUNCTION post_parts_stale() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM post_parts WHERE post_id = NEW.id;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS posts_parts_stale ON posts;
CREATE TRIGGER posts_parts_stale AFTER UPDATE ON posts FOR EACH ROW
    WHEN ((OLD.title, OLD.content, OLD.content_html, OLD.url) IS DISTINCT FROM (NEW.title, NEW.content, NEW.content_html, NEW.url))
    EXECUTE FUNCTION post_parts_stale();
