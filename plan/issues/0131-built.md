# 0131 — Built (Stealth v10.6): Stalker's first edges

Built 2026-11-08 on its own branch, test-first, parts 1–4 of the spec. The owner's two defaults are taken: same-source
author links are edges at `p=0.9`, and same-subject judge edges show as "uncertain" with ✓ / ✗.

**No migration.** The edges are `mx_connections` rows (0068). The owner's marks are `mx_labels` rows of the existing
kind `connection`, with `a` = the newer post and `b` = the older one. F6's connection labels have a task id in `a`, so
the two never meet.

## What was built
- **`markx/graph.py`** (new). Every edge runs from the newer post (`a`) to the older one (`b`). It names its rule or its
  call, carries its evidence, and is closed, never deleted.
  1. **Authors' links** (`sync_links`, `dirty_posts`, `backfill`):
     - Each open, kept `post_refs` row that resolves to a stored post at least 30 days older becomes an edge. It
       resolves the way Connected does: the post at that exact url, else the first one seen at the normalized
       address, never the post itself.
     - The edge is `refers_back`, with rule `author_link_other` (p 1.0) or `author_link_own` (the same source, p 0.9).
       Its evidence is `{href, address, reason, reason_kind}`.
     - Each run re-reads only the newer posts that may have changed since the last one (an hour of overlap):
       - their refs were read again;
       - one of their refs opened or closed;
       - a post stored since sits at one of their links' addresses (so a page fetched later becomes an edge with no
         re-read);
       - one of their edges' refs closed or became boilerplate, or its older post is gone.
     - A link that stops resolving, or becomes boilerplate, closes its edge.
     - The backfill runs inside the decision job, in the run's `connections` stage. It gets 20 s a run, takes 500
       linking posts at a time and can stop and resume (`mx_settings.graph_backfill`). It logs one line a run, and once
       finished it does nothing until `BACKFILL_VERSION` changes. Until it finishes, the incremental pass leaves the
       posts past its cursor to it.
  2. **`relate`** (relate-v1, `post_post`):
     - **Candidates:**
       - the same ent-v3 subject on both sides (one root entity after 0119 A's redirects), with cosine ≥ 0.75 and the
         older post 30–180 days back (`mx_candidates` kind `relate`, source `entity`). They are found for posts whose
         subjects are new or whose entity merged since, plus a one-time sweep;
       - every current author-link edge.
     - **Planning:** `graph.plan` takes the newest newer post first. It adds nothing while `Config.relate_open` (100)
       tasks are open or leased. It runs in the decision run and in the lease (`tasks.PLANNERS["relate"]`, marked
       `# 0131`).
     - **Three runs:** `tasks.record` opens the task again until it has three valid answers. The majority wins, and
       "unknown" stands when no two agree. `p` is the share of runs that agree.
     - **Same-subject verdicts:** a meaningful one becomes an edge with `rule NULL`, its call, and evidence
       `{uncertain, reasons ×3, runs}`.
     - **Author-link verdicts:** the judge only refines the relation (builds_on, follows_up, same_event). Any other
       answer leaves the edge `refers_back`, so a link edge is never removed. A refinement closes the old row and
       opens the new one with the same rule and p.
  3. **next_version from identity:**
     - The newer post's subject is the version right after the older post's subject in the same family. Versions are
       ordered by their numbers, with a leading letter dropped (as `ver_eq` does) and a trailing `.0` dropped.
     - The older post is 30+ days back. The edges go to the predecessor's earliest 3 posts.
     - Rule `entity_next_version`; the evidence holds both entity keys and names. It closes any judge `next_version`
       edge on the same pair.
- **`decide.py`:**
  - `Config.relate_open = 100`.
  - The `connections` stage calls `graph.stage` (its counts are in `counts.graph`).
  - `persist_connections` no longer reads or closes post-to-post rows, because those are the graph's.
- **`schemas.py` / `validate.py`:** the kind `relate` with the answer schema `{reason, relation (the seven), confidence?}`.
  A reason made only of spaces is refused.
- **`guides/relate-v1.md`:** G2's frozen `g2_judge_v3.md`, copied byte for byte (md5 `5a534f99…`, checked by a test).
  It already holds `g2_relations.md`'s definitions word for word, so nothing was added. It names no channel or
  account; its only names are public product names in the next_version examples, left as they are so the md5 holds.
- **`api.py`:**
  - `GET /api/markx/posts/{id}` adds `before` and `before_more`. `before` is the older posts, one row each (an author's
    link first, then identity, then the judge), oldest first, 10 at most. Each row is
    `{post_id, relation, rule, p, reason, uncertain, at, title, source, label}`. `reason` is the same line Connected
    shows.
  - The panel's `connections` drops post-to-post rows, so the list isn't shown twice.
  - `POST /api/markx/labels/edge {newer, older, answer: right | wrong | undo}`.
- **`checks/invariants.py`:** `markx.author_link_resolves`. Every current `author_link_*` edge's `post_refs` row must
  exist, be open and kept, and still resolve to its older post.
- **Frontend:**
  - The Mark X post panel's **Before** section: relation, the older post's link, source, date, what made the edge, and
    the reason line, then "+N more".
  - Uncertain edges carry an "uncertain" mark and ✓ / ✗ (undo after).
  - `frontend/src/services/api.ts` gets one block at the end marked `// 0131` (`markxGraphApi.labelEdge`).
  - The Worker tab lists `relate` in its queue table as it lists every kind; a test covers it.

## Tests
- `test_markx_graph` (18, new):
  - both link kinds; none under 30 days, none for boilerplate, none for an unresolved address;
  - a target stored later;
  - a closed ref and a boilerplate ref each close their edge, which is kept;
  - the backfill resumes and runs once;
  - the decision run never closes graph edges;
  - relate is planned, capped, asked three times and stored uncertain, with the panel and labels;
  - a split is unknown and makes no edge;
  - the window and cosine bounds;
  - the judge refines a link edge (builds_on) and leaves it (background);
  - identity next_version replaces a judge's, and takes the earliest posts 30+ days back;
  - the Before list is capped at 10 with the rest counted;
  - the frozen guide, the schema, the majority rule, G2's render.
- `test_markx_validate`: the kinds set includes `relate`.
- Every `test_markx_*`, plus `test_post_refs` and `test_realdata_checks`: 414 tests, OK.
- Frontend: `components/markx/before.test.tsx` (4); every Mark X test (8 files, 38 tests); `npm run build` (bundle check
  passed: feed +0.87%, post +0.54%).

## The backfill on a server copy (scratch `insight_server_1105_mxreal_sep_check_<pid>_a`, dropped after)
The copy was at migration 0068, so it was migrated to head first, and 0125's refs were read (49,384 posts in 134 s;
248,057 rows, 243,166 open and kept). It was not re-measured on the lab, and the real-data check was not run (the
owner tests on the server).

| | Built | G2's coverage | Difference |
|---|---|---|---|
| `author_link_other` | 1,714 | 1,698 | +0.9% |
| `author_link_own` | 4,637 | 4,631 | +0.1% |
| All | 6,351 | 6,329 | +0.35% |
| Posts on either side | 5,145 | 5,126 | +0.4% |

- **Backfill:** 11.5 s for 36,454 linking posts, peak memory +6 MB (84 MB in all). It fits in one run's 20 s budget.
- **The invariant:** 0 of 6,351 in 0.35 s.
- **The `connections` stage's added time:**
  - a quiet run: 0.47 s;
  - every post dirty: 8.6 s and 73 MB. This happens once, on the first runs after a deploy reads every post's refs.
    An earlier unbatched build took 676 MB here, which is why `sync_links` now works 500 posts at a time.
- **The first run planned 100 relate tasks** (the cap), all of them author-link refinements: the copy's mentions have
  no `entity_id` until a decision run's entities stage links them.

## For the owner
- **The worker:** add `relate` to `DEFAULT_KINDS` after `connect` (it is not in `scripts/markx-worker`; that file was
  not edited here). `PER_CALL` can name `relate=20`, the lab's batch size and the default `--batch`.
- **Cost:** every author-link edge is also a relate candidate (about 6,300 pairs, three runs each, about 19,000 calls).
  They go in 100 open at a time, newest first.
- **Not done:**
  - the re-measure before uncertain edges lose their mark (100+ held-out same-subject pairs);
  - hiding series navigation and "previous issue" links;
  - the owner's review of 30 posts.
- **What could be wrong:**
  - A ref that stops being boilerplate shows no timestamp, so its new edge waits until a later change to that post (or
    a `BACKFILL_VERSION` bump).
  - Same-subject means one root entity. That is identity, not G2's exact lowercased name, so aliases merged by
    identity count too.
