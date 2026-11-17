# 0222 — Stale entity opinions, the owner sees only flags, a post's mention in context

Status: **built on branch (v10.24)**, 2026-11-17. Migration `0156_markx_opinion_inputs_and_flags.sql` (renumber at merge).

## 1. A stale opinion was shown and banded (bug class)

**What the server showed** (GET /api/markx/entities/5935d09d…, 2026-11-17):

| item | pair as shown now | Haiku's answer (stored) | what is true now |
|---|---|---|---|
| 3357ccc1 (11-08, band ≥ 0.90) | "Qwen 14B" (size 14B; 4 posts) = "Qwen3.8FN" (version 3.8, variant FN; 2 posts) | same 0.97: "the same 'Qwen 14B' entity with identical fields; the same two posts appear on each side" | the fields differ and the two sides share no post |
| c777c1b3 (11-08, band ≥ 0.90) | "Qwen3-Max-Thinking" = "Qwen 14B" | same 0.90: "Qwen3-Max-Thinking and 'Qwen 3 Max Thinking' … the examples describe one release" | the B side's posts are about writing style and a trading tool |

**Cause.** Pair questions are keyed by their pair, never by their input: `identity.Asked` ("an asked pair is never asked
again"). The entity behind an id doesn't change. Nothing in the code updates mx_entities' name, type, maker or fields
(only status, parent and shown_name/shown_type). What does change is which posts are linked to the id:
- the relink: every full pass rewrites mx_mentions.entity_id;
- each post read again under a new entities guide (ent-v3 → v4 → v4.2): mx_mention_sets moves the current set;
- owner splits and pins.

The answer is kept anyway. Each run re-decides it from the backlog (`refresh_queued`), and the view shows it with its
band (`_item`). Both items were made in the run of 2026-11-08 00:51 UTC, the first after the v10.7 deploy that switched
the entities guide.

**Not an identity drift.** 5935d09d has always been "Qwen 14B": the page's `aliases` (the members' `name`) say so, and no
code renames an entity. "Qwen 3 Max Thinking" in the second answer is the A side's written form: its posts include
"Вышел новый Qwen 3 Max Thinking". The B side's posts at ask time can't be read through the GETs, because task inputs
aren't exposed. To confirm on the server, read only:
`SELECT t.created_at, t.input FROM mx_entity_queue q JOIN mx_calls c ON c.id = q.call_id JOIN mx_tasks t ON t.id = c.task_id WHERE q.id IN ('3357ccc1-45f5-4b8b-b927-d69b3657eeaa', 'c777c1b3-c3c3-46e9-bfa0-ac71189641a3');`

**How common it is, from the server's open queue.** This is a heuristic on the 17,286 open items read through the
queue GET (one read on 11-17; it won't be repeated: the server is not swept again):
- 20 answers say the posts are the same on both sides; on 16 of them, the two sides' current examples share no post.
- Another clear case: 5cb56d82, "Qwen 397B" = "Qwen3-VL-Reranker" at 0.93, with the evidence "'Qwen 397b' and 'Qwen 397B'
  differ only in casing".

**Fix: an opinion holds only for what it was asked on** (in identity, the module that owns the decision):
- `mx_opinion_inputs`, keyed like a task (kind, input hash), records at ask time each side's head (name, type, maker)
  and the example posts the question quoted (`record_input`, `input_basis`).
- A question asked before this table is read back once from its input text: each example line is matched to the
  side's post on that day by kind, day and title (`derive_inputs`). Measured on prep_mxreal's 4,755 real alias inputs:
  every example was found, 0 void, 0.29 s per 2,000, 80 MB peak.
- `void_opinions` runs before any answer decides (alias, alias2, alias3/4). If a side no longer holds a post it was shown
  (`posts`), its example can't be found (`unmatched`), or its head differs (`head`), the answer is void:
  - it merges nothing;
  - the pair's open item is closed (kept; closed_by `void`, with why);
  - the pair is asked again on its posts now;
  - a void second opinion is dropped from the item.
- New posts on a side never void it: the posts it was shown are still that side's.
- REDECIDE moves to v10.24, so every open item is checked (2,000 a run).
- The queue view checks the shown items without writing (`_voids`): a void item shows no answer, reason, confidence
  or band, only "asked again".

**Automatic merges on stale answers: not counted yet.** The server exposes no task inputs, and the 11-05 clone has no
entities or alias answers, so nothing can be counted there. `identity.opinion_report(cur)` is read only. It counts the
live automatic merges by haiku/second/third whose answer no longer holds today, and among them the merges whose
example post's mention set changed before the merge (those were made on a stale answer). The command is in its
docstring; it is one read on the server, for the operator to run.

## 2. The owner sees only flags

- `mx_entity_queue.flagged_at / flagged_by / flag_note`.
- `POST /api/markx/entities/queue/{id}/flag` with `{flag, note, by: claude|owner}` (`entity_answers.flag`): Claude's
  review flags; nothing else changes.
- `GET /api/markx/entities/queue?view=flagged` is the default; `view=all` is the operator's view. `counts.flagged`, and
  `flagged` on the list.
- The Entities tab shows "Flagged for you: N" with Claude's note on each. The whole queue is a collapsed "Operator
  view", fetched only when opened.
- The entity page shows its flagged questions; the rest of its questions and the old stories to check are collapsed.
- The Worker tab: held tasks and "What is asked" are collapsed as operator controls, and ent-v4.2's label precision is
  collapsed with no labelling prompt.

## 3. A post's mention in context

- The kept entity page's lines about the entity (story posts, loose, citing, recommending) carry `context`: the 2-4
  sentences around the first mention, as parts with every mention marked.
  - Search order: the post's own spans, then the line's names, then the cluster's names.
  - A mention in the text is preferred to one inside a web address.
  - At most 420 characters, from the first 30,000 characters of the shown posts only, in one query.
  - When only the title names it, there is no context (the title stands alone).
- Frontend: under the link, in `<mark>`, in the search snippet's style.
- Measured on a clone of prep_mxreal, full entities pass run there. Build time is in-process, two builds each:

| entity | posts | bytes before → after | build (s) before → after | lines with context |
|---|---|---|---|---|
| Claude Code | 141 | 106,453 → 163,495 (+54%) | 0.06-0.26 → 0.09-0.16 | 126 of 135 |
| OpenAI | 317 | 187,597 → 280,931 (+50%) | 0.09-0.10 → 0.13 | 204 of 227 |
| Claude | 204 | 139,995 → 211,143 (+51%) | 0.08-0.09 → 0.12-0.13 | 149 of 157 |

Peak RSS of the process was 73-129 MB. `CONTEXT_WINDOW` (420) is the knob if the bytes matter. The entity list's
newest posts carry no context, since that would read 600 bodies a request.
