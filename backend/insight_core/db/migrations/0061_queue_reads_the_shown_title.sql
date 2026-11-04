-- 0061_queue_reads_the_shown_title.sql (issue 0076, step 2: one post for everyone)
--
-- The story job reads each post by the title every page shows (post_parts.title, migration 0060),
-- so what the queue keeps of a changed or removed post (story_queue.was, migration 0059: the names
-- its title said are judged again) is that title too, its stored one until it is parsed. The trigger
-- that drops a changed post's parts is renamed so it fires after the queue's (triggers of one event
-- fire in name order), which reads them first.

CREATE OR REPLACE FUNCTION story_queue_post() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO story_queue (key, was) VALUES ('gone:' || OLD.id, jsonb_build_object(
            'title', COALESCE((SELECT pp.title FROM post_parts pp WHERE pp.post_id = OLD.id), OLD.title),
            'source_id', OLD.source_id, 't', COALESCE(OLD.published_at, OLD.fetched_at),
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
        'title', COALESCE((SELECT pp.title FROM post_parts pp WHERE pp.post_id = OLD.id), OLD.title),
        'source_id', OLD.source_id, 't', COALESCE(OLD.published_at, OLD.fetched_at),
        'url', OLD.normalized_url) END)
    ON CONFLICT (key) DO NOTHING;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS posts_parts_stale ON posts;
DROP TRIGGER IF EXISTS posts_then_parts_stale ON posts;
CREATE TRIGGER posts_then_parts_stale AFTER UPDATE ON posts FOR EACH ROW
    WHEN ((OLD.title, OLD.content, OLD.content_html, OLD.url) IS DISTINCT FROM (NEW.title, NEW.content, NEW.content_html, NEW.url))
    EXECUTE FUNCTION post_parts_stale();
