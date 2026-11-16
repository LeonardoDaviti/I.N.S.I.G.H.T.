-- 0143_markx_holds.sql (Stealth v10.20, issue 0210: the re-ask guard)
--
-- 1. mx_tasks.hold: the hold a task was born in ('<kind>:<UTC day>'), or NULL. A planner that adds more than the day's
--    allowance of a kind's tasks (mx_settings `reask_guard_per_day`, default 2,000; new posts' tasks never count and
--    are never held) has the rest held: leased only after every other task (low priority), or never while the owner
--    has stopped the hold (markx/holds.py). A task keeps its key after it is answered (history).
-- 2. mx_holds: the owner's word on a hold, one row a key: `low` (the default when no row: leased last), `stopped` (not
--    leased), `released` (leased as any task; the rest of that day's excess is not held). No row is needed for a task
--    to be held, so a planner's transaction never writes here (no lock shared with a lease).
-- 3. An index by kind and creation time: the guard counts a kind's tasks planned today.
-- Mark X tables only. Idempotent.

ALTER TABLE mx_tasks ADD COLUMN IF NOT EXISTS hold text;

CREATE TABLE IF NOT EXISTS mx_holds (
  key         text PRIMARY KEY,
  kind        text NOT NULL,
  day         date NOT NULL,
  state       text NOT NULL DEFAULT 'low' CHECK (state IN ('low', 'stopped', 'released')),
  changed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mx_tasks_held_idx ON mx_tasks (hold) WHERE hold IS NOT NULL AND status IN ('open', 'leased');
CREATE INDEX IF NOT EXISTS mx_tasks_kind_created_idx ON mx_tasks (kind, created_at);
