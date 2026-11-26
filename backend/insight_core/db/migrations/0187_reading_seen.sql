-- 0187_reading_seen.sql (reading usage: what the reader saw and did not open)
--
-- post_seen: a row the reader saw, at least half of it on screen for a second (the frontend's IntersectionObserver),
-- in News, a track page (brief, tables, topic rows) or a main feed list: one row a post, surface and UTC day, its
-- first and last sighting and how many page loads saw it (the frontend counts a post once a tab, surface and day).
-- Written by POST /api/reading/seen (repo_interactions.record_seen), read by GET /api/reading/summary within its days
-- window. Kept, never pruned. One reader: no user column.
-- Idempotent.

CREATE TABLE IF NOT EXISTS post_seen (
    day       date NOT NULL,
    post_id   uuid NOT NULL REFERENCES posts (id) ON DELETE CASCADE,
    surface   text NOT NULL CHECK (surface IN ('news', 'track', 'feed')),
    first_at  timestamptz NOT NULL DEFAULT now(),
    last_at   timestamptz NOT NULL DEFAULT now(),
    count     integer NOT NULL DEFAULT 1,
    PRIMARY KEY (day, post_id, surface)
);

-- post_interactions needs no new index: the summary reads its window on post_interactions_created_idx (1,586 rows on
-- the 2026-11-19 copy).
