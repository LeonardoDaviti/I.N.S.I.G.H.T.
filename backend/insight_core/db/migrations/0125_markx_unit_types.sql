-- 0125_markx_unit_types.sql (issue 0181, Stealth v10.16 slice K, round 2: a round-up's items typed by the worker)
--
--   mx_unit_type_asks  one row a unit_types task: the round-up post it asks about and the sha256 of each item's text
--                      in key order (u1 = the first): the keys map back to items by their words, so a new split of the
--                      same words (a code change) keeps its answers and is never asked again.
--   mx_unit_types      an item's type, its short headline and whether it only continues the item before it: the first
--                      valid answer for (round-up, text sha) stays; nothing is rewritten or deleted. Read through the
--                      event-type seam (markx/event_types.py: of_units); an own round-up keeps the news types only.
--   mx_roundup_issues  gains what an issue left out (`left_out`: {type: items}, and `continues`), the items still
--                      untyped when it was built, and how many single-curator items the cap left out (`capped`).
--
-- Mark X tables only; no key to a Mark IX table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_unit_type_asks (
  task_id     uuid PRIMARY KEY,
  post_id     uuid NOT NULL,
  texts       text[] NOT NULL,
  asked_at    timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_unit_type_asks_post_idx ON mx_unit_type_asks (post_id);

CREATE TABLE IF NOT EXISTS mx_unit_types (
  id          bigserial PRIMARY KEY,
  post_id     uuid NOT NULL,
  text_sha    text NOT NULL,
  type        text NOT NULL,
  headline    text,
  continues   boolean NOT NULL DEFAULT false,
  task_id     uuid NOT NULL,
  call_id     uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (post_id, text_sha)
);

ALTER TABLE mx_roundup_issues ADD COLUMN IF NOT EXISTS left_out jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE mx_roundup_issues ADD COLUMN IF NOT EXISTS untyped integer NOT NULL DEFAULT 0;
ALTER TABLE mx_roundup_issues ADD COLUMN IF NOT EXISTS capped integer NOT NULL DEFAULT 0;
