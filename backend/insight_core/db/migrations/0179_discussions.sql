-- 0179_discussions.sql (Stealth v10.46, issue 0280: discussions)
--
-- A post's comment thread on a discussion site (Hacker News, Lobsters: ingestion/discussions.py), read in the jobs
-- process (markx/discussions.py) while the thread is young, then never again. Kept, never deleted (a comment a later
-- fetch no longer keeps stays, its seen_at older than the thread's fetched_at).
--
-- discussion_threads: one row per post with a thread. wanted_at: a reader opened the post, or it is in a News row or
-- a track; next_at: its next fetch (null: done); task_id: the newest `discussion` question asked of it.
-- discussion_comments: the comments a fetch kept (at most ingestion/discussions.CAP), in reading order (position).
-- discussion_links: the addresses the kept comments link, read from their HTML (no model), for Related reading and
-- track things later.

CREATE TABLE IF NOT EXISTS discussion_threads (
    post_id        uuid PRIMARY KEY REFERENCES posts (id) ON DELETE CASCADE,
    host           text NOT NULL,
    thread_id      text NOT NULL,
    url            text NOT NULL,
    wanted_at      timestamptz NOT NULL DEFAULT now(),
    wanted_by      text NOT NULL DEFAULT 'reader' CHECK (wanted_by IN ('reader', 'news', 'track')),
    created_at     timestamptz,                 -- the thread's, from the site (else the post's date)
    next_at        timestamptz DEFAULT now(),   -- null: no more fetches
    fetched_at     timestamptz,
    fetches        integer NOT NULL DEFAULT 0,
    failures       integer NOT NULL DEFAULT 0,
    last_error     text,
    total          integer,                     -- comments the site counts
    kept           integer,                     -- comments the last fetch kept
    bytes          integer,                     -- the kept comments' text, in bytes
    asked_kept     integer,                     -- `kept` when the newest question was asked
    task_id        uuid                         -- no key: the mx_* tables are emptied apart (the tests)
);
CREATE INDEX IF NOT EXISTS discussion_threads_next_idx ON discussion_threads (next_at) WHERE next_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS discussion_threads_thread_idx ON discussion_threads (host, thread_id);

CREATE TABLE IF NOT EXISTS discussion_comments (
    post_id     uuid NOT NULL REFERENCES discussion_threads (post_id) ON DELETE CASCADE,
    comment_id  text NOT NULL,
    parent_id   text,
    author      text,
    score       integer,
    at          timestamptz,
    text        text NOT NULL,
    position    integer NOT NULL,
    replies     integer NOT NULL DEFAULT 0,
    seen_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, comment_id)
);

CREATE TABLE IF NOT EXISTS discussion_links (
    post_id     uuid NOT NULL REFERENCES discussion_threads (post_id) ON DELETE CASCADE,
    comment_id  text NOT NULL,
    url         text NOT NULL,
    PRIMARY KEY (post_id, comment_id, url)
);
CREATE INDEX IF NOT EXISTS discussion_links_url_idx ON discussion_links (url);

-- the jobs process's discussions pass has its mx_jobs row (0158's list + 'discussions')
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'news', 'tracks',
                                                                    'unread', 'main_source', 'discover', 'official',
                                                                    'stories', 'entities', 'discussions'));
