-- v10.10.1: ent-v4.2's guide asks for the `published` relation (a issues or publishes document b), but the answer
-- schema's relation list lacked it, so about one ent-v4.2 answer in five was refused and its task failed after three
-- tries. The schema now holds it; this puts those tasks back to open, once, with their tries cleared.
-- Idempotent: a second run finds no task with that error.
UPDATE mx_tasks
   SET status = 'open', attempts = 0, last_error = NULL, lease_until = NULL, leased_by = NULL
 WHERE kind = 'entities'
   AND status IN ('open', 'failed')
   AND last_error LIKE '%''published'' is not one of%';
