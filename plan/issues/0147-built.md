# 0147 Built: track recall, several finders

Built 2026-11-09 on its own branch (Stealth v10.13), on main at a6300d7. **Migration 0094** (`mx_track_probes`,
`mx_track_models`; `mx_track_items.found_by` and `score`; `mx_tasks.subject_kind` may be `track_probe`). Mark X tables
only, no key to a Mark IX table. Private rows (titles, sources, the learned sets, every verdict) stay in
`plan/research/0147-notes.md`.

realdata-check: run at merge.

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | Example posts | `markx/finders.py`: a `probes` task (guide `probes-v1`, schema `{probes 12–20, near_misses ≤ 4}`, `validate._probes`: distinct, not over 600 characters) once per track version (`plan_probes`, `tasks.PLANNERS["probes"]`; the question is the track's header without its examples, so a label does not ask again); its answer becomes `mx_track_probes` rows (`after_answer`); each is embedded by an `embed` task of subject `track_probe` (leased first; a text another probe has is copied) and stored by `embed.store`. A post's probe score is its max cosine to the probes, the description (one probe) and, with labels, the 0145 profile; minus how far its nearest near-miss is closer than that (`probe_score`). Before the probes are embedded the description alone scores, exactly as 0145. |
| 2 | Entities from ✓ items | `learn`: subject / actor keys (`mx_mentions_now`, the entity id or the name key) in 2+ ✓ items and in at most 1% of the last 30 days' posts (10 at least, for a small window); a post naming one as subject or actor fires `entity`. |
| 3 | Domains from ✓ items | Link domains (`post_links`: not boilerplate, not a home page, not a platform) of 2+ ✓ items, linked by at most 1% of the posts; plus the domain classes the track's words name (`DOMAIN_CLASSES`: code hosts, 3D-model sites, each a word pattern; model hubs were measured and left out, see the measure); a post linking one (not its home page) fires `domain`. |
| 4 | Words from ✓ items | `lexicon`: log-odds with an informative Dirichlet prior (Monroe et al.) on document counts, ✓ items against the window's posts, terms in 2+ ✓ items, z ≥ 1.96, the top 30; looked up in `posts.search_vector` and the English layer (`mx_post_search`, 0139); 2+ fire `word`. The units of the ✓ items' reading numbers (`main.numbers`: "tok/s", "gb", "$") in 2+ of them make a post's number with one count as a word. |
| 5 | Source and story priors | A source ✓ 3+ times and in 20%+ of its judged (a verdict or a label) lowers the probe bar by 0.05 for its posts (`source`); a post in a current story (`mx_story_posts`) with a ✓ item fires `story`. |
| 6 | The classifier | After 30 labels (8 of each): logistic regression (plain Python, L2, standardised features) on the post's vector, as its cosines to the ✓ mean, the ✗ mean and the nearest ✓ (a 1,024-weight model on 30–100 labels would only memorise them), plus the probe score without the labels' profile and the finders' hits; each labelled post scored as if it were not labelled (leave-one-out). Retrained when 10 new labels arrive (`mx_track_models`, the old closed with `valid_to`). It orders the candidates; a post no other finder found is one at p ≥ 0.5. |
| — | The union, the bar, the budget | `prepare` (per plan, per track): the probe bar is set so the union passes the same 30% of the last 30 days as 0145 (the other finders' hits counted first, the probes fill the rest, at least half; at most 0.55); from 5 ✓ items, 0145's rule on the probe score (the bar that keeps 98% of the ✓ passing, each scored leave-one-out). The recent pass asks the union in its order (the classifier, else the finders that fired, then the probe score), capped by the per-run budget as before; the history pass reads its pages as before and asks a post when a finder fires. A post the owner labelled is not asked (the label wins). Every passive item records `found_by` and its probe `score` (`cos` stays the description's cosine). |
| — | Adopted finders | `finders.ADOPTED` (or `INSIGHT_TRACK_FINDERS`, comma-separated; the example posts always): see the measure. A finder that is off is still computed for the measure, never fires. |
| — | "found by" | `GET /api/markx/tracks/{id}` items carry `found_by`; the page's `prefilter` adds `probes`, `near_misses` and `found_by` counts. The topic view's meta line carries `found by: example post, entity, domain` on hover (`trackWords.foundByLine`, `TrackTopic.tsx`); design `reader.md`. |

Worker: `probes` in `DEFAULT_KINDS` (before `track`, so a new track's example posts come first), `PER_CALL probes=1`.

## Tests

- `test_markx_finders` (23): the kind, its guide and its answer (12–20, distinct, ≤ 4 near-misses); max-sim with the
  near-miss subtraction; entities in 2+ items and rare; domains of 2+ items, not platforms, not too common, and the
  classes the description names; the lexicon (over-represented, in 2+ items, the top 30); numbers with the items' units
  as a word ("22 tok/s", "24 GB", not "Gbps"); the source prior (3+ and 20%+); what fires (the source's lower bar, the
  word count, the adopted set and the env); the union's order (the classifier, else the count, then the probe score);
  the budget bar (other hits first, the probes keep half, the cap); the classifier's gate (30 labels, 8 of each) and
  its fit. On the test database: probes planned once per version (not per label), asked again for new words, embedded
  as `track_probe` (leased first, priority -1) and stored; the max over the probes beats the description, a near-miss
  pulls a post down; before the probes the description alone (found by `probe`); an entity of two items finds a post
  as subject, not in passing; a domain of two items finds a deep link, not the home page; the items' words and a
  number in tok/s; the source prior lowers the bar, a story sibling fires `story`; `found_by` on items, on the page
  and in its counts; the capped union takes the two-finder post first; the classifier's gate, no retrain at +5, a
  retrain at +10 (the old model closed); it ranks a post like the ✓ above one like the ✗.
- `test_markx_tracks` (25) unchanged and passing: 0145's planner behaviour holds with the description as the only
  probe (the 30% share bar, the history pass, the cap, routing, labels).
- `test_markx_storage` (two tables), `test_markx_validate` (the `probes` kind) updated. All `test_markx_*`: 501 pass; the whole backend suite (`./run-tests.sh`): 2,589 pass, 2 skipped.
- Worker: `scripts/tests/test_markx_worker.py` `TestProbes` (fake-claude): a default kind before `track`, one a call;
  `python3 -m unittest discover -s scripts/tests`: 56 pass.
- Frontend: `components/tracks/tracks.test.tsx` "found by (0147)" (the line, its words, on hover in Discover, none on
  an active item). `npm run build` passes (the feed route +0.27% gzip against the baseline, the topic view its own
  chunk); `npx vitest run`: 77 files, 875 tests pass.

## Measure

On `insight_server_1105_mxreal` as a scratch copy migrated to 0094 (dropped after), the same 30 days as 0145
(2026-10-06 .. 2026-11-05, 5,751 posts, all embedded). The three tracks described as in 0145, no active sources. The
descriptions and the probes embedded by the local llama-server (the description cosines match 0145's to the 3rd–4th
decimal: the copy's build). **The labelled set is 0145's** (the owner's tracks have no labels yet): its rows matched to
posts by title, 181 of 181: project ideas 28 belong / 27 not, local setups 33 / 24, 3D printing 2 / 35. Haiku: 3 probes
calls + 13 judge calls (127 posts, $0.025), 16 in all. Budget = today's: the 30% bar passes 1,725 posts of the month.

**Finders 2–6 learn from ✓ items, so their recall is held out:** 10 random splits, each learning from half the ✓ (and
half the ✗) as labels, recall on the other half's ✓; counts summed over the 10 splits (projects 14 held-out ✓ a split,
setups 17). The classifier's gate is relaxed to 20 labels (8 of each) here: half the set has fewer than 30. Each finder
alone is capped at the budget (in its own order); the unions are ordered as the planner orders them.

**1. Recall on belonged posts, held out, at the same budget (30% of the month) and at 10%:**

| Finder | Projects @30% | Setups @30% | Projects @10% | Setups @10% |
|---|---|---|---|---|
| The description alone (today) | 88/140 (63%) | 126/170 (74%) | 38 (27%) | 78 (46%) |
| 1 Example posts (probe; + the labels' profile) | 115 (82%) | 165 (97%) | 55 (39%) | 113 (66%) |
| 2 Entity | 0 (0%) | 0 (0%) | 0 | 0 |
| 3 Domain | 93 (66%) | 0 (0%) | 82 (59%) | 0 |
| 4 Word (+ numbers' units) | 83 (59%) | 93 (55%) | 76 (54%) | 62 (36%) |
| 5a Source prior | 79 (56%) | 141 (83%) | 68 (49%) | 102 (60%) |
| 5b Story prior | 0 (0%) | 0 (0%) | 0 | 0 |
| 6 Classifier (alone, its order) | 92 (66%) | 170 (100%) | 57 (41%) | 124 (73%) |
| Union of all, by finders fired then probe | 122 (87%) | 170 (100%) | 75 (54%) | 97 (57%) |
| Union of all, ordered by the classifier | 92 (66%) | 170 (100%) | 57 (41%) | 124 (73%) |
| **Adopted: probe + domain + word** | **124 (89%)** | **167 (98%)** | 78 (56%) | 107 (63%) |

What each adds (the union of all, no classifier, at 30%, without that finder): projects: probe −1, domain −15,
word −11, source +2 (it crowds out), entity 0, story 0; setups: probe −14, source −3, domain 0, word 0, entity 0,
story 0. Entities fired for 0–2 posts a split (the ✓ items share no rare subject), stories for 2–21, the source prior
for ~1,300 (one big source holds most ✓), words for ~930–1,040 (setups' lexicon picked launch words from two labelled
laptop posts). The model-hub domain class (setups): no recall at 30% or 20%, −8 points at 10% (hub links ride on model
launches, which then go first as two-finder posts): left out of `DOMAIN_CLASSES`.

**2. Day one (no labels: the description, the probes, the description's domain classes), every belonged post, 30%:**
projects 17/28 → **23/28**, setups 25/33 → **32/33**, 3D printing 2/2 → 2/2 (at 10%: 8 → 13, 15 → 22, 1 → 2).
**End to end** (found and judged `in`; 0145's verdicts plus this run's for the 12 belonged posts 0145 never judged, 11
of them `in`): projects 16/28 → **21/28**, setups 22/33 → **29/33**, 3D printing 1/2 → 1/2. The adopted union shares
764 (projects) and 1,213 (setups) of its 1,725 posts with today's set.

**3. Precision after the judge** (the judge's `in` on new candidates, the union's posts outside today's set; a random
25 a track day one and 25 after split 0's labels, every `in` labelled by the agent from the post's text, 0145's rules):

| Track | Day one | After labels | New candidates | 0145 (today's set) |
|---|---|---|---|---|
| Project ideas | 6/11 | 9/12 | **15/23 (65%)** | 7/11 (64%) |
| Local setups | 7/10 | 7/13 | **14/23 (61%)** | 11/14 (79%) |
| 3D printing | 0 judged in of 15 | — | — | — |

Projects holds. **Setups falls on the new candidates** (small samples, the intervals overlap, but every wrong one is of
one kind): model launches (a 122B release, a ternary small-model release, a 6M image model, an audio-embedding
finetune), a KV-cache paper and a model evaluation, found by the probes and the labels' profile and let in by the judge.

**4. One planner call on the copy** (rolled back): 300 tasks across the three tracks in 2.5 s (each track's finders
0.5–0.7 s; the scoring query read its probe vectors per row before they were materialised: 17–25 s a track).

Caveats: one month of one server copy; the agent's labels, not the owner's; 20 of the projects and 22 of the setups
positives came from 0145's keyword search, which favours the word finder; the ✗ are all from 0145's top-40% sample;
3D printing has 2 belonged posts (finders 2–6 not measurable there). Private rows: `plan/research/0147-notes.md`.

**Adopted by default: probe, domain, word** (`finders.ADOPTED`). Not adopted: entity and story (no recall), the source
prior (−2 / +3: mixed), the classifier as the order (it loses 21 points on projects at 30%, wins 16 on setups at 10%:
not until the owner's labels pass the real gate). Each can be switched on with `INSIGHT_TRACK_FINDERS`.

## Open

- **Setups precision on the new candidates** (61% vs 79%): the judge lets in model launches and a paper for a
  cheap-setups track. A judge change (a model release is out unless the post runs it on its own hardware) is a guide
  version (track-v2) for the owner to decide; it was not made here.
- **The order at small budgets:** at 10% the adopted union trails the probes alone on setups (63% vs 66%): a
  two-finder post goes first whatever its probe score. The per-run cap (300) orders the recent pass, so this matters
  live; weighing the count against the probe score is a measured change for later, not made here.
- **The owner's labels:** re-measure each finder held out once they exist (the classifier at its real gate of 30, the
  source prior, the word finder without keyword-sourced positives). `INSIGHT_TRACK_FINDERS` switches finders on.
- A new track's first plans use the description alone until the worker answers its `probes` task and embeds the
  probes (both leased first); the worker in the main checkout must be updated at merge (`DEFAULT_KINDS`,
  `PER_CALL`), not while it runs.
- A post the owner labelled is no longer asked (the label wins); 0145 asked it.
- "Rare" (entities, domains) is at most 1% of the month's posts and at least 10, so a small window does not shut them.
- `mx_track_items.cos` stays the description's cosine; `score` is the probe score.
