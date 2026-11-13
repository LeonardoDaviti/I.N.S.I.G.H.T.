-- 0121_silent_sources.sql (issue 0178, Stealth v10.16: a source silent far beyond its own rhythm)
--
-- The source doctor's second memory, per source, apart from its failure finding (0032): a fetch that works
-- clears doctor_finding, and a silent source's fetches do work (its old feed still answers, its posts stopped).
--   silent_checked_at: when the doctor last looked where a silent source went (at most once a week);
--   silent_finding: what it found:
--     {"last_post_at", "silent_days", "usual_gap_days", "moved": [{"via", "from", "to"}],
--      "replacement": {"kind": "feed", "url", "title", "latest", "newest", "via"} | null,
--      "stopped": false}
-- The owner's "It stopped" sets stopped; Switch (sources_service.switch_source) clears both. A post newer
-- than the finding's last_post_at makes it stale: the health row ignores it and the next look clears it.
-- Nothing is deleted. Idempotent.

ALTER TABLE source_fetch_state
    ADD COLUMN IF NOT EXISTS silent_checked_at timestamptz,
    ADD COLUMN IF NOT EXISTS silent_finding jsonb;
