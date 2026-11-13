-- 0123_markx_units.sql (issue 0181, Stealth v10.16 slice K: own round-ups, units)
--
-- A round-up (a daily digest, a link list, a long newsletter) is split into its items (markx/units.py):
--   mx_roundups  one row per post the splitter looked at (kept current): whether it is a round-up (`roundup`: its
--                reading says so (`said`), or it has a digest's shape (`structured`), its reading did not see it
--                whole (`read_whole`) and its source is a digest source), where its items came from (`why`:
--                'reading' | 'structure' | 'none'), the adapter that split it, its number of items and words, the
--                basis of the split (the sha256 of the code's version, the reading's call and the post's text), and
--                the issue's time (`issue_at`: its latest attached item's time within two days of the post's own
--                date; NULL while none is). Pairing's post date reads `issue_at` (markx/pairing.py: post_date); the
--                post's own dates are never rewritten.
--   mx_units     the items of each split (post, basis, n): the item's span in the text the splitter read, the
--                pages it links (normalized), its words, the reading's headline when the reading named it, and its
--                time (`at`: its earliest attached post's). A new basis appends a split; the post's current split is
--                the one of mx_roundups.basis. Nothing is deleted.
--   mx_attach    Pairing's `attach` relation: a unit -> a stored post it links, once per source. A digest item,
--                NEVER a voice: no story, News count or corroboration reads this table. Nothing is deleted.
--
-- Mark X tables only; no key to a Mark IX table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_roundups (
  post_id     uuid PRIMARY KEY,
  source_id   uuid NOT NULL,
  version     text NOT NULL,
  basis       text NOT NULL,
  roundup     boolean NOT NULL,
  said        boolean NOT NULL DEFAULT false,
  structured  boolean NOT NULL DEFAULT false,
  read_whole  boolean NOT NULL DEFAULT false,
  why         text NOT NULL CHECK (why IN ('reading', 'structure', 'none')),
  adapter     text CHECK (adapter IN ('list', 'sections', 'lines', 'reading')),
  units       integer NOT NULL DEFAULT 0,
  words       integer NOT NULL DEFAULT 0,
  issue_at    timestamptz,
  split_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  checked_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_roundups_roundup_idx ON mx_roundups (post_id) WHERE roundup;
CREATE INDEX IF NOT EXISTS mx_roundups_version_idx ON mx_roundups (version);
CREATE INDEX IF NOT EXISTS mx_roundups_source_idx ON mx_roundups (source_id);
CREATE INDEX IF NOT EXISTS mx_roundups_issue_idx ON mx_roundups (post_id) WHERE issue_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_units (
  id          bigserial PRIMARY KEY,
  post_id     uuid NOT NULL,
  basis       text NOT NULL,
  n           integer NOT NULL CHECK (n >= 1),
  adapter     text NOT NULL,
  span_start  integer,
  span_stop   integer,
  links       text[] NOT NULL DEFAULT '{}',
  text        text NOT NULL DEFAULT '',
  headline    text,
  at          timestamptz,
  created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (post_id, basis, n)
);
CREATE INDEX IF NOT EXISTS mx_units_at_idx ON mx_units (at);
CREATE INDEX IF NOT EXISTS mx_units_links_idx ON mx_units USING gin (links);

CREATE TABLE IF NOT EXISTS mx_attach (
  id          bigserial PRIMARY KEY,
  unit_id     bigint NOT NULL REFERENCES mx_units(id),
  roundup_id  uuid NOT NULL,
  target_id   uuid NOT NULL,
  source      text NOT NULL,
  found_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (unit_id, target_id, source)
);
CREATE INDEX IF NOT EXISTS mx_attach_target_idx ON mx_attach (target_id);
CREATE INDEX IF NOT EXISTS mx_attach_roundup_idx ON mx_attach (roundup_id);

-- mx_roundup_issues (owner 2026-11-12): INSIGHT's own round-ups, a daily and a weekly, each built once after its
-- period closes (local midnight / local Monday at the mx_settings offset `roundup_tz_offset_minutes`, default UTC+4)
-- and kept: a past issue is never changed; a rebuild is a new version row of the same period. `items`: the digest's
-- ranked items as built (units.digest).
CREATE TABLE IF NOT EXISTS mx_roundup_issues (
  id            bigserial PRIMARY KEY,
  span          text NOT NULL CHECK (span IN ('day', 'week')),
  period_start  timestamptz NOT NULL,
  period_end    timestamptz NOT NULL,
  version       integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  code_version  text NOT NULL,
  roundups      integer NOT NULL DEFAULT 0,
  units         integer NOT NULL DEFAULT 0,
  count         integer NOT NULL DEFAULT 0,
  items         jsonb NOT NULL DEFAULT '[]'::jsonb,
  built_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (span, period_start, version)
);
CREATE INDEX IF NOT EXISTS mx_roundup_issues_period_idx ON mx_roundup_issues (period_start DESC, span);
