-- 0178_track_hidden_posts.sql (Stealth v10.44: a hidden post leaves every track view)
--
-- tracks._items reads no hidden post (posts.filtered_by: its source's item filter or a repair such as
-- hide_listing_pages hid it), so the placements, sections, Discover, counts and kept pages leave it out once the track
-- is placed again. A post hidden or shown again now logs a change of each track that judged it (the worker's and the
-- ingestion's kind, owner false: track_kept.refresh places it again within REFRESH_GAP), as a post moved to another
-- source does (0133). The posts hidden before this migration log one change a track now, so the next refresh places
-- them again. Idempotent.

DROP TRIGGER IF EXISTS posts_track_hidden ON posts;
CREATE TRIGGER posts_track_hidden AFTER UPDATE OF filtered_by ON posts
    FOR EACH ROW WHEN (OLD.filtered_by IS DISTINCT FROM NEW.filtered_by) EXECUTE FUNCTION mx_track_changed_posts();

INSERT INTO mx_track_changes (track_id, owner)
SELECT DISTINCT i.track_id, false
  FROM mx_track_items i JOIN posts p ON p.id = i.post_id
 WHERE p.filtered_by IS NOT NULL;
