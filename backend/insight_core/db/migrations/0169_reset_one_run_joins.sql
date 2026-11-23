-- 0169_reset_one_run_joins.sql (Stealth v10.31, issue 0256: the track check asked twice)
--
-- v10.29 joined a passive `in` on one blind check run; v10.30 asks the check twice (tracks.CHECK_RUNS) and joins only
-- when both runs say in. The one-run joins v10.29 left were to be sent back by the check planner, but only within the
-- check queue's free room, which the backlog kept at 0: they stayed joined (2026-11-21: a steel solar tracker and an
-- air purifier in a 3D printing track). Here, once: every row whose check says in on fewer than two valid runs leaves
-- the track (its check cleared) and its check task is opened again, to be answered a second time. A first `out` is
-- not touched (it settles alone). Mark X tables only; nothing deleted; the check's answers stay in mx_calls.
-- Idempotent: a second run finds no such row.

WITH one AS (
  SELECT i.track_id, i.post_id, i.version, i.check_task_id
    FROM mx_track_items i
   WHERE i.check_in
     AND (SELECT count(*) FROM mx_calls c WHERE c.task_id = i.check_task_id AND c.valid) < 2
), opened AS (
  UPDATE mx_tasks k SET status = 'open', lease_until = NULL, leased_by = NULL
    FROM (SELECT DISTINCT check_task_id FROM one) o
   WHERE k.id = o.check_task_id AND k.status <> 'open'
  RETURNING k.id
)
UPDATE mx_track_items i
   SET check_in = NULL, check_confidence = NULL, check_why = NULL, checked_at = NULL
  FROM one
 WHERE i.track_id = one.track_id AND i.post_id = one.post_id AND i.version = one.version;
