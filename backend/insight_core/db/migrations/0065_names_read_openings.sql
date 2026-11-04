-- 0065_names_read_openings.sql (issue 0076: nothing the stored title said is lost)
--
-- News's names read a post's opening when it has one (post_parts.opening, migration 0064: a name said
-- on a bridge post's second line, which its stored title glued on), so the queue keeps that for a
-- changed or removed post's old names, as load_titles reads them.

CREATE OR REPLACE FUNCTION story_queue_post() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO story_queue (key, was) VALUES ('gone:' || OLD.id, jsonb_build_object(
            'title', COALESCE((SELECT COALESCE(pp.opening, pp.title) FROM post_parts pp WHERE pp.post_id = OLD.id), OLD.title),
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
        'title', COALESCE((SELECT COALESCE(pp.opening, pp.title) FROM post_parts pp WHERE pp.post_id = OLD.id), OLD.title),
        'source_id', OLD.source_id, 't', COALESCE(OLD.published_at, OLD.fetched_at),
        'url', OLD.normalized_url) END)
    ON CONFLICT (key) DO NOTHING;
    RETURN NEW;
END $$;
