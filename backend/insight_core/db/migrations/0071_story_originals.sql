-- 0071_story_originals.sql (issues 0114 and 0123: a story's original fetched when INSIGHT lacks it)
--
-- 1. source_fetch_state gains 0114's early fetch: linked_wanted_at (when a story's link to one of the source's
--    pages made it due: the schedule's fetch_linked decision, until a fetch succeeds after it), linked_url (that
--    page) and linked_fetched_at (when the last early fetch was decided: one per scheduled interval).
-- 2. story_originals: one row per page asked for, never asked again (the address, without tokens):
--    kind 'fetch_linked' (0114: its source fetched early) or 'collect' (0123: the page itself, one request, or
--    a tweet from the quote a member holds, none). outcome: wanted, found, missing (the feed didn't hold it),
--    collected, unreadable, failed, or the reason none was made (walled, no_article, tweet_unheld). requests:
--    what it cost (0 or 1); the shared budget counts them over 24 hours. Kept, never deleted.
--
-- Idempotent.
ALTER TABLE source_fetch_state
    ADD COLUMN IF NOT EXISTS linked_wanted_at timestamptz,
    ADD COLUMN IF NOT EXISTS linked_url text,
    ADD COLUMN IF NOT EXISTS linked_fetched_at timestamptz;

CREATE TABLE IF NOT EXISTS story_originals (
    kind text NOT NULL CHECK (kind IN ('fetch_linked', 'collect')),
    url text NOT NULL,
    source_id uuid REFERENCES sources(id) ON DELETE SET NULL,
    story_id uuid,
    post_id uuid,                 -- the post it found or stored (no foreign key: a log, never merged by 0038)
    asked_at timestamptz NOT NULL DEFAULT now(),
    requests integer NOT NULL DEFAULT 0,
    outcome text NOT NULL,
    detail text,
    settled_at timestamptz,
    PRIMARY KEY (kind, url)
);
CREATE INDEX IF NOT EXISTS story_originals_asked_idx ON story_originals (asked_at);
