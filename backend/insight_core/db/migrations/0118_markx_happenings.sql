-- 0118_markx_happenings.sql (issue 0175, Stealth v10.16 slice H: stored happenings)
--
-- mx_happenings: a post's happening key (markx/happening.py) as it was computed from one reading and the post's
-- mentions then: the reading's guide and call, the action group the reading names (`read_group`, the event-type
-- seam's, before parties refine it), the key (`grp`, NULL when the reading names no happening: a roundup, an action
-- that names none, fewer than 2 separate parties), its parties (resolved entity roots or "name:<name key>",
-- unordered: stored sorted), stage, stated day (`at`) and money amounts (sorted). `basis` is the sha256 of every
-- input the key was computed from (the code's version, the reading's call, each current mention's guide, number and
-- root): a row whose basis no longer matches is computed again. A key that changes adds a row; a key that stays
-- updates its basis in place. Readers take the newest row per post (highest id). Keep everything: no row is deleted.
--
-- Mark X tables only; no key to a Mark IX table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_happenings (
  id            bigserial PRIMARY KEY,
  post_id       uuid NOT NULL,
  guide         text NOT NULL,
  reading_call  uuid,
  version       text NOT NULL,
  basis         text NOT NULL,
  read_group    text,
  grp           text,
  parties       text[] NOT NULL DEFAULT '{}',
  stage         text,
  at            date,
  money         double precision[] NOT NULL DEFAULT '{}',
  computed_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
  checked_at    timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_happenings_post_idx ON mx_happenings (post_id, id DESC);
CREATE INDEX IF NOT EXISTS mx_happenings_grp_idx ON mx_happenings (grp) WHERE grp IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_happenings_parties_idx ON mx_happenings USING gin (parties);
CREATE INDEX IF NOT EXISTS mx_happenings_checked_idx ON mx_happenings (checked_at);

-- The newest row of each post: what every reader reads.
CREATE OR REPLACE VIEW mx_happenings_now AS
SELECT DISTINCT ON (post_id) * FROM mx_happenings ORDER BY post_id, id DESC;
