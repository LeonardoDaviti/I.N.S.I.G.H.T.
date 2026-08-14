-- 0017_milestones.sql
-- MILESTONES: a succession tree of landmark releases in a field.
--
-- THERE IS NO `milestones` TABLE, AND THAT IS THE DESIGN.
-- A milestone is (lane, version) grouped out of `posts` at request time. At this
-- scale persisting derived nodes buys nothing and costs: a derive job that can be
-- switched off (how `topics` died at 0 rows), a write path the user must discover
-- (how `stories` died at 0 rows), stale-sweep/upsert-guard/lock-field machinery, and
-- a render that disagrees with the corpus until the next run. Editing a lane pattern
-- below fixes the entire history instantly because there is no history to migrate.
--
-- SCOPING REUSES folders/source_folders VERBATIM (0013_folders.sql, 0016_tracks.sql).
-- There is no milestone<->source membership table. A scope resolves through
-- folders_service.list_source_ids(folder_id); folder_id NULL means "all non-arXiv
-- sources", which is the default landing scope because the two best release sources
-- in this corpus (tg.i-c-a.su/rss/seeallochnaya, .../denissexy) are in NO folder.
--
-- TRANSACTION SAFETY: backend/insight_core/db/migrate.py applies every pending
-- migration on ONE cursor and commits once, so this file contains no VACUUM, no
-- CREATE INDEX CONCURRENTLY and no ALTER TYPE ... ADD VALUE. Every statement is
-- IF NOT EXISTS or ON CONFLICT DO NOTHING, so re-running is a no-op.

-- =====================================================================
-- 1. milestone_lanes - the ONLY stored knowledge. Data, not code.
-- =====================================================================
-- A lane is one lineage: one column of the tree, one succession chain.
--
-- match_pattern is a POSIX regex applied to
--     coalesce(title_pivot, lower(title)) || ' ' || coalesce(summary_pivot,'')
-- (title_pivot is lower(title), NOT a translation - so patterns are lowercase and
--  the Russian Telegram posts match on the latin product name inside Cyrillic text).
--
-- It MUST contain exactly one capturing group, which captures the version token.
-- Postgres substring(text FROM pattern) returns that group:
--   substring('вышел opus 5, кодит почти как fable 5' from
--             '\m(?:claude opus|opus)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M')  ->  '5'
--
-- THE ALIAS ALTERNATION IS LOAD-BEARING. '(?:claude opus|opus)' is why the English
-- "Introducing Claude Opus 5" and the Russian "Вышел Opus 5" land on the SAME node.
-- A generic \m(\w+)[ -]v?([0-9]+) extractor splits them into two nodes and the
-- cross-source corroboration count - the only real importance signal in this corpus
-- - collapses to 1. Do not "simplify" this into one regex.
--
-- folder_id NULL = global vocabulary (applies to every scope).
-- folder_id set  = lane only exists inside that folder/track. This is how the
--                  "Smart Glasses Development" track gets ('Ray-Ban Display','Meta'),
--                  ('Vision Pro','Apple') with no code change.
CREATE TABLE IF NOT EXISTS milestone_lanes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  folder_id     UUID NULL REFERENCES folders(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,              -- 'Claude Opus' -> node titles are name || ' ' || version
  vendor        TEXT NULL,                  -- 'Anthropic'   -> the grouping column in the UI
  match_pattern TEXT NOT NULL,              -- one capturing group, see above
  lane_order    INTEGER NOT NULL DEFAULT 999,
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One lane name per scope. COALESCE because UNIQUE treats NULLs as distinct and we
-- need exactly one global 'GPT'.
CREATE UNIQUE INDEX IF NOT EXISTS milestone_lanes_scope_name_uidx
  ON milestone_lanes (COALESCE(folder_id, '00000000-0000-0000-0000-000000000000'::uuid), name);
CREATE INDEX IF NOT EXISTS milestone_lanes_folder_idx
  ON milestone_lanes (folder_id, lane_order) WHERE enabled;

-- =====================================================================
-- 2. milestone_overrides - the ONLY thing a user writes. Correctly empty by default.
-- =====================================================================
-- node_key is deterministic and computed, never generated:
--     'release:<lane_id>:<version_label>'      e.g. release:8f3e...:5.6
--     'paper:<post_id>'
-- Empty table = nothing hidden, nothing pinned, nothing renamed. That is the correct
-- zero state, unlike a `milestones` table whose zero state is "feature is broken".
--
-- custom_title is the one curation guarantee we make: a title the user typed is never
-- overwritten, because nothing ever writes titles.
CREATE TABLE IF NOT EXISTS milestone_overrides (
  node_key     TEXT PRIMARY KEY,
  state        TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'hidden' | 'pinned'
  custom_title TEXT NULL,
  note         TEXT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (state IN ('active', 'hidden', 'pinned'))
);

CREATE INDEX IF NOT EXISTS milestone_overrides_state_idx
  ON milestone_overrides (state) WHERE state <> 'active';

-- =====================================================================
-- 3. Seed the global vocabulary. 20 rows.
-- =====================================================================
-- The lanes that match nothing today cost one Values-scan row each and light up the
-- day the corpus sees them.
--
-- \m and \M are Postgres word-boundary escapes (start-of-word / end-of-word). They
-- are what stops '\mgpt...' matching inside larger tokens and what stops the version
-- capture running into '0731' in 'DeepSeek-V4-Flash-0731' (captures '4').
INSERT INTO milestone_lanes (folder_id, name, vendor, match_pattern, lane_order) VALUES
  (NULL,'Claude Opus',  'Anthropic','\m(?:claude opus|opus)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',      10),
  (NULL,'Claude Sonnet','Anthropic','\m(?:claude sonnet|sonnet)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',  11),
  (NULL,'Claude Haiku', 'Anthropic','\m(?:claude haiku|haiku)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',    12),
  (NULL,'Claude Fable', 'Anthropic','\m(?:claude fable|fable)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',    13),
  (NULL,'Claude Mythos','Anthropic','\m(?:claude mythos|mythos)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',  14),
  (NULL,'GPT',          'OpenAI',   '\mgpt[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                       20),
  (NULL,'OpenAI o',     'OpenAI',   '\mopenai o([0-9]+(?:\.[0-9]+)?)\M',                         21),
  (NULL,'Gemini',       'Google',   '\mgemini[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                    30),
  (NULL,'Gemma',        'Google',   '\mgemma[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                     31),
  (NULL,'Llama',        'Meta',     '\mllama[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                     40),
  (NULL,'DeepSeek',     'DeepSeek', '\mdeepseek[ -]?[vr]?[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',        50),
  (NULL,'Kimi',         'Moonshot', '\mkimi[ -]?k?[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',               60),
  (NULL,'Qwen',         'Alibaba',  '\mqwen[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                      70),
  (NULL,'Grok',         'xAI',      '\mgrok[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                      80),
  (NULL,'Mistral',      'Mistral',  '\m(?:mistral|magistral|devstral)[ -]?v?([0-9]+(?:\.[0-9]+)?)\M', 90),
  (NULL,'GLM',          'Zhipu',    '\mglm[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                      100),
  (NULL,'MiniMax',      'MiniMax',  '\mminimax[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                  101),
  (NULL,'Nova',         'Amazon',   '\mnova[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                     102),
  (NULL,'Command',      'Cohere',   '\mcommand[ -]?r?[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',           103),
  (NULL,'Ernie',        'Baidu',    '\mernie[ -]?v?([0-9]+(?:\.[0-9]+)?)\M',                    104)
ON CONFLICT DO NOTHING;
