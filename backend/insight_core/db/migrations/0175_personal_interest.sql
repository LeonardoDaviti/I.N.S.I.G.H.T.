-- 0175_personal_interest.sql (Stealth v10.42: the personal ranking layer, markx/personal.py)
--
-- 1. mx_interests: the reader's "More" / "Less" taps (and the seeds of their stated interests), one row a tap, kept,
--    never deleted: what (`dim`: thing = an entity, kind = a kind of news, source = a source; `key` its id or the kind's
--    key; `name` as shown), the answer (more, less, none = "not a reason", undo = back to what INSIGHT learned), where
--    it was taught (the News row, the post) and who (`origin`: reader | seed). The newest row of a (dim, key) counts.
-- 2. mx_interest_weights: what the jobs process learned from the reader's reads (opens, read time, read to the end,
--    kept, Later) and their tracks, one row a (dim, key): a derived cache, replaced at each learn. Small: only keys
--    whose weight is not zero.
--
-- Mark X tables only; no key to a Mark IX table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_interests (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dim         text NOT NULL CHECK (dim IN ('thing', 'kind', 'source')),
  key         text NOT NULL,
  name        text,
  answer      text NOT NULL CHECK (answer IN ('more', 'less', 'none', 'undo')),
  row_id      uuid,
  post_id     uuid,
  origin      text NOT NULL DEFAULT 'reader' CHECK (origin IN ('reader', 'seed')),
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_interests_key_idx ON mx_interests (dim, key, created_at DESC);

CREATE TABLE IF NOT EXISTS mx_interest_weights (
  dim         text NOT NULL,
  key         text NOT NULL,
  weight      real NOT NULL,
  name        text,
  why         jsonb NOT NULL DEFAULT '{}'::jsonb,
  learned_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (dim, key)
);
