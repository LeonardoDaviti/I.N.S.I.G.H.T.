-- 0056_removed_sources.sql (issue 0072, C3)
--
-- Removed sources stay removed. Removing a source remembers its address and when; an address a
-- source was switched away from (the source doctor's Switch, issue 0036) is remembered the same
-- way. Importing a file (sources.json, scripts/sync_sources_json.py json-to-db) never adds a
-- remembered address back. Adding the source again from the app forgets it.
-- Keyed as the import compares sources: the platform and the address as stored. Nothing is
-- remembered for sources removed before this migration: their removal left no trace.

CREATE TABLE IF NOT EXISTS removed_sources (
    platform TEXT NOT NULL,
    handle_or_url TEXT NOT NULL,
    removed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (platform, handle_or_url)
);
