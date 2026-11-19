-- 0163_markx_task_inputs_spent.sql (Stealth v10.25, issue 0233; 0216 item 1, never built in v10.22).
--
-- An answered task's input may be spent: markx/tasks.py `spend` (the scheduler's daily work) sets mx_tasks.input to
-- NULL for the kinds nothing reads once answered (tasks.SPENDS), 14 days after the answer. The input's hash stays:
-- the (kind, guide, input_hash) dedupe, mx_inc_inputs and every hash reader are unchanged.
--   1. input becomes nullable;
--   2. the hash check holds for every input that is there.
-- The new check is implied by the old one, which every row passed, so it is added NOT VALID: no scan of the table under
-- the migration's lock (it is enforced on every insert and update from now on). The mx_tasks_counted_upd trigger (0132)
-- writes no delta for these updates (kind and status unchanged). Space comes back to the OS only by a VACUUM FULL of
-- mx_tasks, the owner's step (DEPLOYMENT.md); a plain VACUUM makes it reusable inside the table. Nothing is deleted.
-- Idempotent.

ALTER TABLE mx_tasks ALTER COLUMN input DROP NOT NULL;
ALTER TABLE mx_tasks DROP CONSTRAINT IF EXISTS mx_tasks_input_hash_is_the_input;
ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_input_hash_is_the_input
  CHECK (input IS NULL OR input_hash = encode(sha256(convert_to(input, 'UTF8')), 'hex')) NOT VALID;
