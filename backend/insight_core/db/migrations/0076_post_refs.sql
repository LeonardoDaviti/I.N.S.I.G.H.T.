-- 0076_post_refs.sql (issue 0125: Connected on every post, Earlier / Later / Outside INSIGHT, no model)
--
-- 1. post_refs: one row per (post, linked address) for every http(s) link of a post's text (utils/post_refs.py:
--    body_hrefs, made absolute and normalized as posts.normalized_url is). href: as the text has it; position: 0
--    for the post's first address. reason / reason_kind: the line the author gave for it, by the measured rule
--    (quote: the words the post quotes from the page, sentence: the sentence around the link, link_words: link
--    words that name a page); the stored post's title (the rule's step 3) is read with the row. boilerplate: the
--    link is its source's signature (in 25% of its posts, 4 or more), set by the story job's signature pass.
--    Resolved at read time by address (posts.url or posts.normalized_url), so a target stored later is a row with
--    no re-run. Keep everything: a link gone from a post's text is closed (valid_to), never deleted; one back is
--    open again.
--    An address can be longer than a btree row holds: the row is unique on md5(target_address) and looked up by a
--    hash index (equality only, no length limit).
-- 2. posts.refs_scanned_at: when the post's refs were read (ingestion's post writer, the story job's link reading,
--    and the one-off backfill of the posts stored before: StoriesService.fill_refs, 500 posts a transaction,
--    resumable). NULL: not read yet.
-- 3. The Reddit fix: post_links.extract_links now decodes escaped HTML (no raw <a href, &lt;a present) as the reader
--    does. The posts stored so are read again by the story job's link reading (links_scanned_at NULL): their new
--    links queue them for the story job (migration 0059's trigger on post_links).
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS post_refs (
  post_id        uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  target_address text NOT NULL,
  href           text NOT NULL,
  position       integer NOT NULL,
  reason         text,
  reason_kind    text CHECK (reason_kind IN ('quote', 'sentence', 'link_words')),
  boilerplate    boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  valid_to       timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS post_refs_post_address_idx ON post_refs (post_id, md5(target_address));
CREATE INDEX IF NOT EXISTS post_refs_target_idx ON post_refs USING hash (target_address);

ALTER TABLE posts ADD COLUMN IF NOT EXISTS refs_scanned_at timestamptz;
CREATE INDEX IF NOT EXISTS posts_refs_unscanned_idx ON posts (id) WHERE refs_scanned_at IS NULL;

UPDATE posts SET links_scanned_at = NULL
 WHERE links_scanned_at IS NOT NULL
   AND strpos(content_html, '&lt;a') > 0
   AND content_html !~* '<a\y[^>]*?href=["'']';
