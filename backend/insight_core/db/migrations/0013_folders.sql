-- 0013_folders.sql
-- Folders: a grouping layer over sources. An expert runs over a folder.

CREATE TABLE IF NOT EXISTS folders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  description TEXT NULL,
  system_prompt_default TEXT NULL,
  sort_order INTEGER NOT NULL DEFAULT 999,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS folders_sort_idx ON folders(sort_order, name);

CREATE TABLE IF NOT EXISTS source_folders (
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  folder_id UUID NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, folder_id)
);

CREATE INDEX IF NOT EXISTS source_folders_folder_idx ON source_folders(folder_id);
CREATE INDEX IF NOT EXISTS source_folders_source_idx ON source_folders(source_id);
