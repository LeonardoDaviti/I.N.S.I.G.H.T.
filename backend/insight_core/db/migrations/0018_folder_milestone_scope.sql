-- 0018_folder_milestone_scope.sql
-- Let a folder/track opt out of the global milestone lane vocabulary.
--
-- 0017 seeds 20 global lanes (folder_id IS NULL) for AI model families, and
-- repo_milestones.list_lanes matches `folder_id IS NULL OR folder_id = <scope>`, so those
-- lanes apply to EVERY scope. In a curated track that is wrong: the Smart Glasses track's
-- Reddit and YouTube sources routinely mention GPT and Claude, so the track's milestone
-- rail filled with "GPT 5.6" and "Claude Opus 5" - true matches, but not what that track
-- is about.
--
-- Default TRUE preserves today's behaviour for every existing folder. Deciding this by
-- folder.kind instead would be invisible magic; an explicit column is predictable.

ALTER TABLE folders
  ADD COLUMN IF NOT EXISTS use_global_milestone_lanes BOOLEAN NOT NULL DEFAULT TRUE;
