-- 0108_markx_scale_marks.sql (Stealth v10.14: Mark X at the scale of "every post read")
--
-- mx_plan_marks: a post a planner read and passed over (markx/plan_marks.py): its input repeats an asked one
-- (`same_input`) or the cite cue rule passed it (`not_cue`), with its text stamp then. The planners (read, entities,
-- cite) skip a post while its mark's stamp is its stamp now, so a planner with nothing to add no longer reads
-- every such post again on each call (the server's cite planner: 84 s a run for nothing added). Derived rows: kept,
-- overwritten when the post is passed over again.
--
-- Mark X tables only. Idempotent.

CREATE TABLE IF NOT EXISTS mx_plan_marks (
  kind       text NOT NULL,
  guide      text NOT NULL,
  post_id    uuid NOT NULL,
  why        text NOT NULL CHECK (why IN ('same_input', 'not_cue')),
  stamp      text NOT NULL,
  marked_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, guide, post_id)
);
