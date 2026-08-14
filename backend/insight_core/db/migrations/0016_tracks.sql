-- 0016_tracks.sql
-- TRACK = a folder with a digest switch and optional keyword narrowing.
--
-- Deliberately NOT a new table. Everything a track needs already exists as a folder:
-- source membership is source_folders (M2M), and scoped post retrieval is
-- posts_service.get_posts_by_sources_and_range, already used by experts. A separate
-- tracks table would duplicate source_folders verbatim and leave two membership models
-- to keep in sync - which is how the stories feature ended up unreachable.

-- 1. Folders become typed: 'folder' (generic grouping) or 'track' (curated interest).
ALTER TABLE folders ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'folder';

-- 2. The track's declared intent for the main digest. This is what the UI toggle writes.
--    It is a bulk action over member sources, NOT the query-time authority (see 4).
ALTER TABLE folders ADD COLUMN IF NOT EXISTS exclude_from_main_digest BOOLEAN NOT NULL DEFAULT FALSE;

-- 3. Optional narrowing inside the track's sources. Empty array = take everything the
--    member sources publish.
ALTER TABLE folders ADD COLUMN IF NOT EXISTS match_keywords TEXT[] NOT NULL DEFAULT '{}';

-- 4. THE query-time switch, on sources so there is exactly one answer per source.
--    source_folders is many-to-many: if the flag lived only on the folder, a source in an
--    excluded track AND a normal folder would have no defined answer, and every resolution
--    rule is bad ("any excluded folder wins" means adding TechCrunch to a track silently
--    removes TechCrunch from the main digest).
--    enabled = FALSE stops ingestion entirely.
--    in_main_digest = FALSE keeps ingesting but hides the source from daily/weekly digests.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS in_main_digest BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS folders_kind_idx ON folders(kind);
CREATE INDEX IF NOT EXISTS sources_in_main_digest_idx ON sources(in_main_digest) WHERE in_main_digest = FALSE;

-- 5. Drop the dead column while we are here. Nothing reads folders.system_prompt_default:
--    experts_service uses expert['system_prompt'] exclusively. The writers are removed in
--    the same commit.
ALTER TABLE folders DROP COLUMN IF EXISTS system_prompt_default;
