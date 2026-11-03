-- 0059_incremental_stories.sql (issue 0072 A: the incremental story job)
--
-- 1. post_edges: the connections the story rules find (story_rules.Edge), one row each: a post
--    joins a post or an outside page by a reason (address, text, title, link, citation, thread,
--    quote) or lists it as a roundup (mention). Stories are the groups these make; the story job
--    writes them, and the incremental job reads them (a thread's replies, the pages a story is
--    joined through). `weight` is 1 for every rules edge (no certainty is measured yet), `made_by`
--    the rules' stamp, `verdict` Mark X's "same story?" answer. `dst_story` is for a post's
--    membership of several stories (0072's draft, "a post in several stories"): unused yet, keyed
--    already, so those edges are rows of this table.
-- 2. story_keys: what each post can join or change another by (story_rules.keys, and the names in
--    its title for News: "n:"), so the job finds the posts a new one touches by an index.
-- 3. story_queue: the posts saved, changed or removed since the last story run, written by
--    triggers, so the job regroups only what they touch. `was` keeps what a changed or removed
--    post was (its title, source, time and address; a removed one's keys).
-- 4. news_surges: each name's surges (news_rules.surges, per name), kept so a run judges again only
--    the names a new title says.
-- 5. story_posts.position, news_posts.position: each post's place in its story's order, where a
--    date alone counts as that day's earliest timed post (issue 0072 D).
-- The first start after it regroups every story (the rules' stamp changed), in batches.

CREATE TABLE IF NOT EXISTS post_edges (
    src_post UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    dst_post UUID REFERENCES posts(id) ON DELETE CASCADE,
    dst_url TEXT,
    dst_story UUID REFERENCES stories(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1,
    evidence JSONB,
    made_by TEXT NOT NULL,
    verdict TEXT CHECK (verdict IS NULL OR verdict IN ('yes', 'no')),
    CHECK (num_nonnulls(dst_post, dst_url, dst_story) = 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS post_edges_key ON post_edges (src_post, kind, COALESCE(dst_post::text, dst_story::text, dst_url));
CREATE INDEX IF NOT EXISTS post_edges_dst_post_idx ON post_edges (dst_post) WHERE dst_post IS NOT NULL;
CREATE INDEX IF NOT EXISTS post_edges_dst_url_idx ON post_edges (dst_url) WHERE dst_url IS NOT NULL;

CREATE TABLE IF NOT EXISTS story_keys (
    key TEXT NOT NULL,
    post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    PRIMARY KEY (key, post_id)
);
CREATE INDEX IF NOT EXISTS story_keys_post_idx ON story_keys (post_id);

CREATE TABLE IF NOT EXISTS story_queue (
    key TEXT PRIMARY KEY,          -- post:<id> (saved or changed), gone:<id> (removed), redo:<id> (a rule change)
    was JSONB,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS news_surges (
    name TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL,
    posts UUID[] NOT NULL,
    usual INTEGER NOT NULL,
    PRIMARY KEY (name, at)
);

-- Discover counts again only the keys a story run's posts link (issue 0072 A).
CREATE INDEX IF NOT EXISTS discover_addresses_key_idx ON discover_addresses (key);

ALTER TABLE story_posts ADD COLUMN IF NOT EXISTS position INTEGER;
ALTER TABLE news_posts ADD COLUMN IF NOT EXISTS position INTEGER;

CREATE OR REPLACE FUNCTION story_queue_post() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO story_queue (key, was) VALUES ('gone:' || OLD.id, jsonb_build_object(
            'title', OLD.title, 'source_id', OLD.source_id, 't', COALESCE(OLD.published_at, OLD.fetched_at),
            'keys', (SELECT COALESCE(jsonb_agg(key), '[]') FROM story_keys WHERE post_id = OLD.id)))
        ON CONFLICT (key) DO NOTHING;
        -- its story's other posts regroup without it
        INSERT INTO story_queue (key)
        SELECT 'post:' || o.post_id FROM story_posts sp JOIN story_posts o ON o.story_id = sp.story_id
        WHERE sp.post_id = OLD.id AND o.post_id <> OLD.id
        ON CONFLICT (key) DO NOTHING;
        RETURN OLD;
    END IF;
    INSERT INTO story_queue (key, was) VALUES ('post:' || NEW.id, CASE WHEN TG_OP = 'UPDATE' THEN jsonb_build_object(
        'title', OLD.title, 'source_id', OLD.source_id, 't', COALESCE(OLD.published_at, OLD.fetched_at),
        'url', OLD.normalized_url) END)
    ON CONFLICT (key) DO NOTHING;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS posts_story_queue_insert ON posts;
CREATE TRIGGER posts_story_queue_insert AFTER INSERT ON posts FOR EACH ROW EXECUTE FUNCTION story_queue_post();
DROP TRIGGER IF EXISTS posts_story_queue_update ON posts;
CREATE TRIGGER posts_story_queue_update AFTER UPDATE ON posts FOR EACH ROW
    WHEN ((OLD.title, OLD.content_hash, length(OLD.content), OLD.content_html, OLD.url, OLD.normalized_url,
           OLD.published_at, OLD.fetched_at, OLD.author, OLD.reposted_by, OLD.metadata ? 'page_update', OLD.source_id)
          IS DISTINCT FROM
          (NEW.title, NEW.content_hash, length(NEW.content), NEW.content_html, NEW.url, NEW.normalized_url,
           NEW.published_at, NEW.fetched_at, NEW.author, NEW.reposted_by, NEW.metadata ? 'page_update', NEW.source_id))
    EXECUTE FUNCTION story_queue_post();
DROP TRIGGER IF EXISTS posts_story_queue_delete ON posts;
CREATE TRIGGER posts_story_queue_delete BEFORE DELETE ON posts FOR EACH ROW EXECUTE FUNCTION story_queue_post();

CREATE OR REPLACE FUNCTION story_queue_link() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO story_queue (key) VALUES ('post:' || COALESCE(NEW.post_id, OLD.post_id)) ON CONFLICT (key) DO NOTHING;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS post_links_story_queue ON post_links;
CREATE TRIGGER post_links_story_queue AFTER INSERT OR UPDATE OR DELETE ON post_links
    FOR EACH ROW EXECUTE FUNCTION story_queue_link();
