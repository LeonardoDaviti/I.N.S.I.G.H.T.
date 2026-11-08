-- 0088_reference_links.sql (issue 0137: new spheres, round 2)
--
-- B8 (N13). A full text's reference list is not its links. post_links.kind: 'reference' for a link inside the
--   text's references or bibliography section (utils/post_links.reference_spans: a heading so named, or an element
--   whose class or id says so), 'link' for every other. A reference row is boilerplate too, so no story, News,
--   Discover or Mark X rule reads it, and the signature pass keeps it so (StoriesRepository.mark_boilerplate);
--   Connected lists them folded (PostRefsRepository._references). Search-engine links (scholar.*, /search?q=,
--   /?term=) are no longer kept at all (post_links.is_search_link).
--   Every existing row is 'link' (the default). The posts whose stored HTML may hold a references section or a
--   search link are read again by the story job's normal path (links_scanned_at NULL: fill_missing_links, a batch a
--   run): their links become exactly what extract_links reads now. Nothing is deleted but the rows extract_links no
--   longer keeps for those posts (search links), as any re-read of a post's links does.
ALTER TABLE post_links ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'link'
    CHECK (kind IN ('link', 'reference'));
CREATE INDEX IF NOT EXISTS post_links_reference_idx ON post_links (post_id) WHERE kind = 'reference';

UPDATE posts SET links_scanned_at = NULL
WHERE links_scanned_at IS NOT NULL AND content_html IS NOT NULL
  AND (content_html ~* '<h[1-6][^>]*>\s*(<[^>]+>\s*)*([0-9ivx.]+\s+)?(references?|reference list|bibliography|works cited|cited works|literature( cited)?|references cited|notes and references|references and notes|sources and references|список литературы|литература|библиография)\s*:?\s*(<[^>]+>\s*)*</h[1-6]'
       OR content_html ~* '<(ol|ul|section|div|aside)\s[^>]*(class|id)\s*=\s*["''][^"'']*(references|bibliography|citations|ref-list|reflist)'
       OR content_html ~* 'href\s*=\s*["'']https?://scholar\.');
-- (Narrowed at merge: a stored post whose only change would be another search page's link is not read again here;
--  its links are read by today's rules whenever it is next read. Fewer rows change: the reference lists, scholar.)

-- B9 (N14). An undated feed item is dated by when INSIGHT first saw it: posts.published_precision 'seen'. 0063's
--   column CHECK (named posts_published_precision_check by Postgres) allows it now. No row is rewritten.
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_published_precision_check;
ALTER TABLE posts ADD CONSTRAINT posts_published_precision_check
    CHECK (published_precision IS NULL OR published_precision IN ('exact', 'date', 'none', 'seen'));
