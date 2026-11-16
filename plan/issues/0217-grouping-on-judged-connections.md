# 0217: Stories grouped on judged connections, every join checked against the story's core (Stealth v10.23, experiment spec)

Status: **spec only**. Nothing is built here. Branch `v1023-core-spec` from main (v10.21, 00221ab5). This file holds the
experiment: what is tested, against what, on which data, by which bars, and when we drop it. The bars and the decision
rule below are written **before** anything is measured; they are not changed once the held-out windows are read.

Real names from the server stay in the private notes (`plan/research/grouping-0217/`, gitignored). The names here are
invented: *Vela 5* is a model release by *Acme Labs*; *Northwind* is a company whose CEO resigns; *Orbit* is a company
that goes public.

Vocabulary is the codebase-design skill's: **module**, **interface**, **depth**, **seam**, **adapter**, **leverage**,
**locality**, **the deletion test**. Domain words are GLOSSARY.md's (Pairing, Relation, Voice, Happening, Event type,
Party, Stage, Anchor, Round-up).

Reads: [0203](0203-ship-or-drop.md) (the runaway row, the v10.18 fix, the 1g method),
[0205](0205-mark-x-news-main.md) (Mark X News main; the IPO fix; stale connections; order independence),
[0208](0208-news-ranked-for-the-reader.md) (significance; a row's main story speaks for it),
[0209](0209-decision-runs-held.md) and [0215](0215-db-and-rebuild-speed.md) (run time and memory baselines),
[0212](0212-ent-v5-one-reading.md) (ent-v5: one reading per post, event type and entities in one answer).

---

## 1. The problem, as a class

### 1.1 What happened

Three cases, all from the server (2026-11-07..12). The rows are in the private notes.

1. **The runaway row** (0203 1g). One Mark X News row held 397 posts. It was led by the Vela 5 release. Through
   chained joins it swallowed about 57 coherent Mark X stories: Northwind's CEO resignation and the scandal before it
   (~100 posts), two releases from another lab, Orbit's IPO, and two benchmark launches. The chain was not inside the
   stories (no story held two happenings). It was in how stories become rows.
   - A digest post inside the Vela 5 story said "Vela 5 is out; Northwind's CEO resigns after 33 years".
   - The CEO's surging name was in that post's title, so the CEO's stories joined Vela 5's row.
   - A post that was in two stories glued two more, and so on.
   - v10.18 patched it in `news_rules.news` with three rules:
     - "core names only": a surging name joins a story's post only if the name says one of the story's core names;
     - "a post in one row": a post in several stories counts only in its first story's row;
     - "large stories join only on the main name + a judged connection": two stories of 5+ posts each join only by
       a name that says each one's main name, and, for Mark X, only if the judge connected them.
2. **The IPO in four rows** (0205 2b). The judge had connected Orbit's three IPO stories (12, 7 and 5 posts). The row
   was still built per surge, from the surge's *first post*. That post belonged to the Vela 5 story, which each IPO
   story refused. So the three stories that agreed with each other never met. v10.18 patched the loop: each member
   now tries every group the surge has reached so far.
3. **Stale judged connections** (0203, 0205 §3). 16 of 94 `same_event` story connections described members their
   stories no longer held. The story ids had kept answers about posts that had moved. v10.18 added a shown-members
   stamp (`decide.holds`).

Measured after the v10.18 fix, on the six days 11-07..12 (0203, blind):

| | Mark X (v10.18+) | Mark IX |
|---|---|---|
| rows that are a single story | **83%** (75–89), 98/118 | 94% (87–97), 91/97 |
| rows not a duplicate of another row | **86%** (79–92), 102/118 | 73% (64–81), 71/97 |
| clean major rows | 33 | 20 |
| major events missed | 0 | 14 |

Mark X fixed duplication but still mixes more than Mark IX: 20 of 118 rows contain something off-story. 0203 traced
most of these to the stories' own joins (the judge's pairs), not to News chaining.

### 1.2 The class

These are two failures of one shape.

- **Greedy transitive joins.** Every grouping step in the pipeline is a **union-find over any accepted edge**. One
  edge between *any member* of A and *any member* of B makes A and B one group. Nothing asks whether the edge holds
  against what A is *about*. So a group's reach is the transitive closure of its members' weakest links: a digest, a
  reply, a citation, or a name said in passing. The more members a group has, the more surface it exposes, so large
  groups grow faster. That is the runaway.
- **Rows built from rule keys, not from the judge's verdicts.** A News row is made from surging *names* and shared
  *posts*. The judge's story-to-story verdicts (`same_event`, `development`, `different`) only enter as a **veto** on
  one case (two large stories). They never *build* a row. A `different` verdict never *prevents* a join through
  another path. So:
  - the IPO stays split although the judge said "same event": no name path reached all three stories;
  - a row can hold two stories the judge called `different`: a name path reached both.

The v10.18 patches are three special cases, each added after one failure. Each one narrows one edge type. None of
them changes the shape: single-linkage over heterogeneous edges, with the judge on the side.

### 1.3 Where it lives (main v10.21)

The same shape appears in three places.

1. **Mark IX's stories, rule edges** (`backend/insight_core/utils/story_rules.py`).
   - `_UnionFind` is defined at lines 185–197.
   - `grouping()` (398–607) unions posts on text, title, address, citation, link, thread and quote (`join` at 441,
     `chain` at 444–457, citation at 502–510, thread/quote at 519–520).
   - Mark X starts from these stories (decide.py's rule 1). The links are evidence, not verdicts.
2. **Mark X's stories, judge edges** (`backend/insight_core/markx/decide.py`).
   - `decide()` (363–483) works in three steps:
     - joins and pairs are accepted per question (412–432);
     - pair-stories that share a post are glued by a second union (433–453);
     - `same_event` merges at `tau_merge` are applied by `alias[drop] = keep` (455–473), which is transitive: if A≡B
       and B≡C then A≡C, even if A vs C was asked and answered `different`.
   - Joins are judged against `side(key)`: the story's first three reports (`plan_pass1`, 227–325; `tasks.STORY_MEMBERS
     = 3`, `tasks.py:63`; inputs at `tasks.py:487–510`). That is "the earliest members", not the story's core. The
     earliest member can itself be a round-up.
   - Typed connections (`connections`, 1154–1209) are asked over `pairing.story_pairs` and kept while their shown
     members hold (`holds`, 1221–1229).
3. **News rows** (`backend/insight_core/utils/news_rules.py`).
   - `news()` (359–482) builds a `_UnionFind` (374) over posts:
     - a story's posts are unioned to the story (380–388; "a post in several stories: the lowest story id's");
     - then every surging name unions the posts it holds (438–449);
     - the guards are `holds` (432–436, core names), `join` (395–410, the large-story rule with `judged`),
       `core_names` (336–346), `main_name` (349–356), `CORE_SHARE`/`LARGE_POSTS` (54–59).
   - Mark X calls it through `markx/news.rows_of` (131–173). `judged` comes from `built._connected` (`news.py:165`,
     `built.py:208–214`, relations `CONNECTED = development, follows_up, same_event`, `built.py:40`), passed through
     `NewsService.rows` (`services/news_service.py:75–87`).
   - Mark IX calls the same function with `judged=None`.
   - The incremental path `_changed_rows` (`news.py:192–245`) rebuilds only the closure a change reaches (rows,
     stories, surges). Its cost scales with the size of the largest group that a change touches.

### 1.4 The current interfaces

- `news_rules.news(posts, stories, found, *, judged=None) -> List[NewsStory]`.
  - The type signature is small.
  - The real interface is not. A caller must also know:
    - five module thresholds (`CORE_SHARE`, `LARGE_POSTS`, the name rules);
    - that a post in two stories goes to the lowest story id;
    - that `judged` vetoes only large-large joins, and only for Mark X;
    - that `judged` must hold current members (otherwise stale answers act; 0205 had to fix `rows_of` passing
      "new:" ids);
    - that the result is order-independent only because the inputs are sorted first (0205).
- `decide.decide(posts, stories, answered, config, events) -> Outcome`. Merges, glue and joins are all decided here,
  each with its own transitive rule. A `different` answer has no effect on the grouping.
- `built._connected(cur, story_ids) -> Set[FrozenSet[str]]` is a third place that reads judge edges, as a set of
  allowed pairs.

So the decision "which things are one row" has **no single owner**. Its facts are spread over four modules. That is
poor **locality**: the IPO bug lived in the *interaction* between `news_rules`' join order and `decide`'s connections,
and each fix landed where the symptom was.

### 1.5 The deletion test, today

- **Delete `news_rules.news`'s guards** (`holds`, the large-story `join`, "one row per post"). The runaway comes back
  (0203 replayed it: 397 posts). They earn their keep, but only as patches: each one is a special case of "does this
  edge hold against the group's core?", written three times in three forms (core names, main name, judged pair).
- **Delete `decide`'s alias/glue unions.** Merges stop. That complexity is real and has to live somewhere.
- **Delete `built._connected`.** The large-story guard loses its judged half. Its only caller is `rows_of`, so it is
  a pass-through that turns the judge's graph into a veto set.

What the test shows: the complexity is real, but it is spread over three shallow pieces (a union-find with ad-hoc
guards in each). The experiment asks whether one **deep module** that owns "these items form one group, and here is
each group's core" would be both more accurate and smaller than the sum of those pieces. If it is, the three guards,
the glue and `_connected` disappear into it.

---

## 2. The design under test

### 2.1 The story's core

A **core** is what a group is *about*. It is computed from members, but it is not the members. It is a small value,
and joins are tested against it.

| part | from | rule (initial; swept in §3) |
|---|---|---|
| **lead posts** | `news_rules.lead` / Mark X's lead | the lead, plus up to `k_lead` earliest *reports* that are not round-ups and not replies (`units.roundup_sql`; thread/quote reason) |
| **main subjects** | the current mention set (`repo.current_guide`, so ent-v4.2 or ent-v5, whichever is current), resolved to root entities (identity) | entities whose role is subject in ≥ `core_share` of the lead posts' mentions, plus those the lead names as subject; most specific of a family (version over family, as `core_names` does for names) |
| **main name** | surges (`news_rules.main_name`) | kept as a fallback for posts with no reading yet |
| **event type** | the event-type seam (`event_types.of_posts`, `of_stories`), never raw reading fields | the majority closed type among the lead posts and its happening group (`action_group`) |
| **happening key** | `mx_happenings` (parties, action group, stage) when the post has one | parties resolved to root entities; the **stage** is kept apart from the rest of the key |
| **time span** | post dates (Pairing's `post_date`) | first post, and the lead posts' span |

The core is recomputed whenever the members change. It is **stable by construction**: a reply, a digest, or one late
post cannot become a lead post. Only reports can, and only the earliest `k_lead`. So the core changes only when the
story's own reporting changes.

### 2.2 A join holds against the core, never via one member

An edge *e* between item *x* (a post or a group) and group *G* is **admitted** only if it holds against *G*'s core:

1. **The edge's endpoint in G is a lead post**, or the edge's evidence names a main subject of *G* as *x*'s main
   subject (not as a mention). A digest member of *G* that names Northwind's CEO is not a lead post, and the CEO is
   not *G*'s main subject. So the edge from the CEO story to that digest is not admitted, whatever its type.
2. **Compatible event**. *x*'s event type and happening group do not conflict with *G*'s:
   - same group, or one is unknown;
   - a release and a resignation conflict;
   - a release and its benchmark result go to §2.5 (drift), not to a plain join.
3. **No cannot-link**. No judged `different` at ≥ `tau_diff` exists between *x* (or *x*'s lead posts) and *G*'s lead
   posts.
4. **Group-to-group joins are symmetric**. For two groups, (1)–(3) must hold in both directions: core against core,
   never member against member.

Rule edges (thread, quote, same address, same text) are the exception to (1). They are **attachments**, not joins. A
reply or quote attaches to the group of the post it replies to, but it can never *bridge* two groups: an attached post
is not an endpoint for any other edge's admission. That is the general form of 0203's "a post in one row" and of
`check_threads`' reason (one thread can hang unrelated replies on a story; `decide.Config`, the S5 review's W1).

### 2.3 Clustering over judged edges, not union-find over any edge

Each admitted edge gets a signed weight:

| edge | weight (initial; swept) |
|---|---|
| judge `same_event`, p | `+w_same · logit(p)` (positive above p = 0.5) |
| judge `development` / `follows_up` | 0 for grouping; it becomes a **typed connection** (and a sub-event, §2.5) |
| judge `different`, p | `−w_diff · logit(p)`; at ≥ `tau_diff` it is a hard **cannot-link** |
| judge `reaction` (join of a post) | `+w_react`, only post→group, never group↔group |
| `mention` / `digest_item` | 0 (the post is a mention of the group, as today) |
| rule: thread, quote, address, same text | attachment (above), never a bridge |
| rule: citation, link | `+w_cite`, admitted only under §2.2 (1) |
| surging name | `+w_name`, admitted only if the name says *both* cores' main subject or main name |
| unasked pair | 0 (unknown: no evidence either way; never treated as `different`) |

There are two algorithms to compare (the parameter `algo`):

- **Constrained average-linkage agglomeration** (`algo=agg`).
  - Start from attachments (posts + their replies/quotes) and Mark IX's link stories.
  - Repeatedly merge the pair of groups with the highest *average* admitted weight between their lead posts, while it
    is > `theta`, with no cannot-link between them, and with §2.2 holding in both directions.
  - Ties break by (weight, smaller first-post id).
  - Average linkage means one strong edge from one member cannot carry a 57-story group. Many edges, or edges at the
    core, are needed.
- **Correlation clustering, deterministic pivot + local search** (`algo=cc`).
  - KwikCluster with pivots taken in a fixed order: by lead-post id hash. The order is a function of the inputs only.
  - Then up to `ls_rounds` of single-item moves that raise the sum of within-group weights.
  - Cannot-links and §2.2 are hard constraints throughout.

Both must be **order-independent**: the same inputs in any order give the same partition. This is a hard gate (§5).

The output is **one partition at two levels**. Stories are groups of posts. News rows are groups of stories, made by
the same procedure with the row-level edge set (story↔story judge verdicts, names). One interface serves both levels;
only the edge set differs.

### 2.4 How rule edges and judge edges combine

- **Rules propose, the judge disposes.**
  - Link, thread and citation edges stay first evidence (decide.py rule 1). They seed groups and admit attachments.
  - A judged `different` at ≥ `tau_diff` overrides any rule bridge between two cores.
  - A judged `same_event` at ≥ `tau_merge` joins two groups even if no name or link reaches them. That fixes the IPO
    class without a special loop.
- **Stale verdicts act only while they hold.** A verdict counts only while the members its question showed are still
  in the groups it joins. This is 0205's `holds`, moved inside the module and applied to every judge edge, not only to
  connections.
- **Where the judge saw only earliest members.** Today's join, merge and connect inputs show the earliest
  members (`STORY_MEMBERS = 3`, `CONNECT_MEMBERS = 5`). Parameter `shown`:
  - `earliest`: today's inputs. The default, and the only option that adds no Haiku question.
  - `core`: the lead posts, plus each main subject's best post. This is a new input, so new tasks. It is measured as
    a one-time re-ask of the windows (cost in §7) and adopted only if it beats `earliest` by the §5 bars.

### 2.5 When the core drifts

Example: the Vela 5 launch turns into a controversy (a safety finding, then a recall). Is that one row or several?

- **What the core sees.** The lead posts say "release". Later reports say "security"/"policy" about the same main
  subject. The subject is the same, the event type conflicts, and the judge says `development`.
- **Policy `drift=split`** (the default to test). The later posts form their own group with their own core. The two
  groups are linked by a typed `development` connection. News shows two rows, and the later one says "follows Vela 5's
  release" (the existing connection UI). This is what rule C ("main subject only") and the late-post table (decide.py
  rule 7) already imply.
- **Policy `drift=nest`.** One row whose core is the *first* event. Each drifted group is a **sub-event** inside it,
  ordered by time: the list → tree direction of `list-tree-graph`.
  - In the experiment this changes only how rows are *counted* and labelled. The page does not change.
  - A labeller is shown the parent and its sub-events and asks "one row with parts, or separate rows?".
  - A UI for nesting is a later slice, and only if `nest` wins.
- **What the core never does: move.** A group's core is computed from its lead posts. A drifted sub-group cannot
  replace it. A story never gets re-led by its controversy (as 0111's "never re-led by its second post").

### 2.6 The deep module and its seam

**Proposal: a new module `backend/insight_core/utils/grouping.py`, pure functions, no database.**

```
group(items, edges, *, policy) -> Grouping
    items:  Item(id, kind=post|story, at, lead=bool, subjects, event, happening, attach_to)
    edges:  Edge(a, b, source=rule|judge|name, relation, p, shown)
    policy: Policy(algo, theta, tau_diff, k_lead, core_share, drift, weights...)   # one frozen value
Grouping:
    groups:   [Group(id, members, core, sub_events)]
    rejected: [(edge, why)]          # every edge not admitted, with its reason: core, cannot-link, stale, bridge
```

- **Interface.** One function, one policy value, and an output that explains itself: `rejected` turns "why isn't X
  in this row" into a lookup, not a trace. Invariants a caller relies on:
  - order-independent;
  - deterministic;
  - every item in exactly one group;
  - a group's core is computed from its own lead posts only;
  - linear-ish in edges (no all-pairs step).
- **Depth.** Behind it sit:
  - the core;
  - admission;
  - attachments;
  - staleness;
  - both algorithms;
  - drift;
  - the tie rules.

  Today these are spread over `news_rules.news` (guards), `decide.decide` (alias, glue), `built._connected` and
  `decide.holds`.
- **Seam and adapters.** The seam is the `edges` and `items` the caller passes. There are two real adapters today, so
  the seam is real:
  - **Mark IX**: rule and name edges only, no judge;
  - **Mark X**: rule, name and judge edges.

  A third adapter, the offline experiment harness (frozen edges from a dump), is the test surface. The harness and the
  unit tests cross the same seam as production does.
- **Callers after adoption** (not in this experiment):
  - `news_rules.news` becomes: build items and edges from stories and surges, call `group`, then score and tally;
  - `decide.decide` hands its accepted verdicts to `group` in place of alias and glue;
  - `built._connected` and the large-story guard are deleted;
  - `holds` moves inside.
- **Why not deepen `news_rules` itself?** It owns *names and scoring*. Putting the story-level partition there would
  make Mark X's decide depend on a News module. So the partition gets its own owner, and `news_rules` becomes one of
  its callers. That keeps to "no parallel path": one grouping, two levels.
- **The deletion test, after.** Delete `grouping.py`: union-finds with guards reappear in three callers. Delete one
  caller's adapter: nothing else changes. That is the shape we want.

---

## 3. Arms

All arms run the same frozen inputs (§4). They differ only in the grouping step. The stories' own joins and checks
(decide's per-question accept rules, checks, the late table) are unchanged in every arm, so differences come from
grouping alone.

| arm | stories (post level) | News rows (story level) |
|---|---|---|
| **A0 control** | v10.21 as is: decide alias + glue, Mark IX links | `news_rules.news` v10.21 (core names, one row per post, large-story guard with `judged`) |
| **A0′ historical** | as A0 | `news_rules.news` before v10.18 (no guards): only to confirm the replay still reproduces the runaway (397) and the IPO split (4) |
| **B core-checked joins** | union-find as today, but every edge must pass §2.2 admission (attachments, cannot-links, core) | the same admission on story↔story edges; the v10.18 guards removed (B must subsume them) |
| **C judged-edge clustering** | §2.3 clustering over the edges as today's guards admit them (no core admission) | the same, at story level; judge `same_event` builds, `different` cannot-links |
| **D both** | §2.2 admission + §2.3 clustering | the same |

The parameters swept, on the **dev** window only (§4). The held-out windows run the single setting chosen on dev:

| parameter | values |
|---|---|
| `algo` (C, D) | `agg`, `cc` |
| `theta` (merge threshold, agg) | 0, 0.5, 1.0, 2.0 |
| `tau_diff` (cannot-link) | 0.6, 0.75, 0.85, off |
| `k_lead` (lead posts) | 1, 2, 3, 5 |
| `core_share` (main subjects) | 0.34, 0.5, 0.67 |
| `w_cite`, `w_name` | {0.5, 1, 2} × {0, 0.5, 1} |
| `drift` | `split`, `nest` |
| `shown` (judge inputs) | `earliest` (default, no questions), `core` (one-time re-ask; D only) |
| subjects from | current mention set (ent-v4.2) / ent-v5 Shadow rows where present / surging names only |

The sweep is a grid of roughly 2 × 4 × 4 × 4 × 3 × 9 × 2 ≈ 6,900 settings per arm. Every setting is a pure function
over frozen edges, so the whole grid runs in minutes. The setting is chosen on dev by the §5 primary score, with ties
going to the simplest (fewest non-default values).

---

## 4. Data

### 4.1 Windows

| window | days | role | why |
|---|---|---|---|
| **dev** | 2026-11-07..12 | tuning; fully known | holds the runaway (from 11-07) and the IPO; 0203's 118 + 97 labelled rows are reusable as a check |
| **H1 held out (older)** | 2026-11-01..06 | first held-out read | before the patches; mined as `held-out-testing` says (unseen stories from older server posts) |
| **H2 held out (fresh)** | the 7 days after the code and guides are frozen (≈ 2026-11-17..23) | the decision | nobody has looked at it; written down before it exists |
| **scale** | `prep_scale` copy (148k posts) | time and memory only | no labels; the worst-case group sizes |

H1 and H2 are labelled only after the dev setting and the §5 bars are committed (a commit on this branch, hash
recorded in the results).

### 4.2 How to get them (read only; nothing written on the server)

- **Path A, preferred: a read-only dump.** A `pg_dump` of the `mx_*` tables (stories, memberships, connections,
  tasks and answers, readings, mentions, happenings), `posts`, `post_parts`, `post_refs`, `news_*` and `sources`,
  restricted to the windows ± 30 days. Restored as a scratch copy (`prep_mx1123`) on the disposable test Postgres
  (`agent-test-load`). It has the **negative** verdicts (`different`, refused merges) that clustering needs, and the
  real `shown` members. Taking it is a server action, so it needs the owner's go (`server-deployment`).
- **Path B, fallback: the 0203 method.** Light, cached, read-only GETs:
  - `/api/markx/news?all=1` (the rows);
  - `/api/markx/posts/{id}` (each post's Mark X stories with role, reason, judge words; its reading, entities and
    connections);
  - Mark IX's `/api/news`.

  0203's `replay.py` showed this rebuilds `news_rules.news` faithfully (it gave back 397, 67, 44, 41…). It does
  **not** carry refused verdicts. So for arms C and D, Path B re-asks the candidate story pairs (`pairing.story_pairs`
  over the rebuilt stories, the same policy rows) offline with the **frozen** guides (`judge-story-v1`, `connect-v1`)
  through the worker's own prompt and parser, as 0208 did. About 1.5 questions per pair (asked again on a split, as
  `settle` does).
- Either way, the inputs are frozen to one JSON per window: items, edges with their source, and the shown members.
  Every arm reads that file, and nothing else.

### 4.3 Freezing

- **Code.** The harness and `grouping.py` prototype live in `plan/research/grouping-0217/` (private). Their commit
  hash is recorded before H1 is read. Control A0 runs main's own `news_rules.news` and `decide.decide`, imported from
  the checkout at v10.21's hash.
- **Guides.** `judge-story-v1`, `connect-v1`, `judge-read-v1`, `judge-raw-v1`, as they are on main. No guide edit
  during the experiment. A guide change is its own experiment.
- **Readings.** For subjects and event types, the current set as of the dump. ent-v5 rows are used only in the
  "subjects from" sweep, never mixed in silently.
- **The bars and decision rule** (§5) are this file, committed now.

---

## 5. Metrics, bars, labelling, decision

### 5.1 Metrics (0203's definitions, plus pair-level and engineering ones)

Row-level, from blind labels:

- **single-story**: the share of rows whose posts are all one story (rule C: main subject only).
- **not a duplicate**: the share of rows with no other row of the same window telling the same story.
- **clean major rows**: rows labelled major that are single-story and not a duplicate.
- **major events missed**: a major event the other arms' pages show as a row, which this arm has no row for (it may
  be buried inside another row).

Pair-level, from blind labels on sampled post pairs:

- **joins lost**: among pairs that A0 puts in one row and labellers call the same story, the share the arm splits.
- **joins wrongly kept/made**: among pairs the arm puts in one row, the share labellers call different stories
  (B-cubed precision over the sample).

Engineering, measured, no labels:

- **order independence**: 20 random shuffles of items and edges per window. The partition must be identical every
  time.
- **stability**: replay H2 hour by hour (each hour's frozen inputs). Measure the share of rows whose lead post is
  unchanged and whose members' Jaccard is ≥ 0.8 between consecutive hours, and the count of rows that split and later
  re-merge (flapping).
- **decision-run time**: the decision run's `questions and decisions` + `news` stages on the dump copy, median of 5;
  and the incremental `_changed_rows` closure size (posts reached per change).
- **peak memory**: VmHWM via `utils/peak.py`, reset per run. Baselines (0215):
  - decide, full run on mxreal: 172 MB;
  - news job: 72 MB;
  - a rebuild slice: 494 MB;
  - plus the same runs on this dump under A0.
- **Haiku questions per day**: questions each arm's policy would add or remove per day at H2's volume. `earliest`
  arms should add 0.

### 5.2 Labelling protocol (blind)

- **Labellers.** Two independent Claude subagents per item. Each gets its own shuffle, and arm names are hidden
  (rows from all arms are pooled, deduplicated by membership, and named P/Q/R/S at random per day as in 0203). Each
  labeller sees the post titles, sources, dates and opening text (up to 1,500 characters per post, the full text for
  the lead), never a verdict, an edge, a score or an arm. Where the two disagree, a third breaks the tie, and the
  disagreements are reported. Cohen's κ is reported per metric. The labellers are one model family, so the agreement
  is likely correlated (0208's note).
- **Questions.**
  - Per row: one story? which posts are off (ids)? major? duplicate of which row?
  - Per pair: same story / development / different / can't tell.
  - Per nested row (`drift=nest`): one row with parts, or separate rows?
- **Labels are pooled across arms.** A row with the same members in two arms is labelled once. Every row that differs
  from A0 in any arm is labelled.
- **Sample sizes.**
  - Rows: all rows of H1 and H2 for each arm. Expected ~120 per window per arm, ~240 per arm; pooled distinct rows
    ~400. At p ≈ 0.9 and n = 240, a Wilson interval is about ±4 points.
  - Pairs: 300 pairs per window that A0 joins (for joins lost; 0/300 has a Wilson upper bound of about 1.3%), plus
    200 pairs per arm that the arm joins and A0 doesn't, plus 200 that A0 joins and the arm doesn't.
- **Statistics.** Wilson 95% intervals for every proportion. For arm vs control on the same rows' posts, a paired
  bootstrap over days (1,000 resamples) for differences, because rows are not paired across arms.

### 5.3 Bars and the decision rule (fixed now, read on H1 ∪ H2; H2 alone must not reverse it)

An arm **ships** (it becomes the grouping, behind `grouping.py`, through its own build slice) only if **all** of
these hold:

1. **Single-story ≥ 90%** with a Wilson lower bound ≥ 85%, *and* at least A0's + 4 points (bootstrap 95% CI of the
   difference > 0). For reference, A0 measured 83% on dev and Mark IX 94%.
2. **Not a duplicate ≥ A0 − 2 points.** Splitting must not bring Mark IX's duplicates back. A0: 86%.
3. **Clean major rows ≥ A0's**, and **major events missed ≤ A0's** (A0: 0 on dev).
4. **Joins lost ≤ 3%** of A0's real same-story pairs (Wilson upper bound ≤ 5% on 300+ pairs).
5. **Order independence: 100%** (20/20 shuffles on every window). A hard gate, no exception.
6. **Stability ≥ A0's**, and no more flapping rows than A0.
7. **Run time ≤ A0's** (median; `questions and decisions` + `news`) and **peak RSS ≤ A0's** on the same copy. Must
   not exceed v10.21's.
8. **Haiku questions per day ≤ A0's.** The `shown=core` setting may ship only if its one-time re-ask pays back within
   the measured accuracy gain *and* its steady state adds no questions per day (a new task only when the core
   changes).

If two arms pass, prefer the one with fewer parameters set away from the defaults. If both still tie, prefer B (a
smaller change). If D passes and B does not, D. If C passes alone, C ships only with the core admission kept as a
Shadow count (we want to know why it didn't need it).

`drift=nest` vs `split`: `nest` wins only if labellers prefer one-row-with-parts on ≥ 70% of nested rows (Wilson
lower bound ≥ 60%). Otherwise `split` is the default, and nesting is not built.

**Results format** (`report-breakage-format`): for each arm, the rows **built right / wrong / missed** with exact
rows (post → what the arm did → label), the cause and the fixing feature. These go in the private notes; the issue
gets the counts.

---

## 6. Risks, failure modes, and what drops the idea

- **Over-splitting.** Strict cores can split a real story whose lead is thin: a two-report story whose lead is a
  tweet with no reading. Watch joins lost (bar 4) and duplicates (bar 2). Mitigation to sweep: a post with no reading
  falls back to its main name (surges).
- **The core is only as good as the readings.**
  - Entities: 94% right uniformly; new entities 89% (0203 1a).
  - Event types are what read-v3 or ent-v5 say.
  - A wrong main subject in the lead makes a wrong core, and that error now gates joins instead of just being one
    edge.
  - Measure on the subset of rows whose lead has no or a wrong subject (labelled).
  - If the arms' gains vanish there, the core needs the judge's `shown=core` input, or it fails.
- **Cannot-links from bad `different` answers.** A hard negative is strong. A wrong `different` at high p splits a
  real story for good. Swept via `tau_diff`. Measured as joins lost explained by a cannot-link (from `rejected`).
- **Unasked pairs.** Clustering treats unknown as 0, so recall depends on what Pairing proposes. If many real
  same-event pairs are never asked (the IPO's stories were asked, but others may not be), C and D can't join them,
  and A0's name paths did. Watch: joins lost whose pair has no verdict.
- **Instability.** The core moves when lead posts change, and average-linkage results can flip as edges arrive. Bar 6
  catches it. Mitigation: hysteresis (a group keeps a member until the average falls below `theta − δ`). Swept only if
  stability fails.
- **Cost of the incremental path.** Clustering over a closure can be larger than union-find's. `_changed_rows`
  reaches every row a change touches, so a bigger closure means a slower incremental run. Bar 7.
- **The dev window is the one we know.** The runaway is fixed in A0 already. On fresh days the arms compete with the
  v10.18 guards on the residue (20/118 mixed rows), which is a smaller effect, harder to show. That is why bar 1 asks
  for +4 points and not more, and why H2 is fresh.
- **Labeller bias.** One model family, correlated (0208). Two labellers + κ + a third on ties. Cases whose verdict
  flips the bar get the owner-style reader review (`reader-review-each-version`) before a ship.

**We drop the idea if any of these holds:**

- No arm passes bars 1–3 on H1 ∪ H2 (the guards are as good as a principled grouping, so keep the patches).
- The best arm needs more Haiku questions per day than A0 (bar 8), or more memory or time (bar 7), with no setting
  that avoids it.
- Order independence or stability cannot be met without a rule written for a specific site or name
  (`generalize-not-overfit`).
- H2 reverses H1: the arm passes on H1 and fails a bar on H2. Then the gain was the older days', and the idea waits
  for Mark X's graph (Stalker), where groups come from typed edges by design.

If dropped, keep: the frozen windows, the labels (a test set for the next grouping change), and the `rejected`
explanation idea, as a debugging view over A0 (cheap and useful on its own).

---

## 7. Cost and time

| step | who | time | money |
|---|---|---|---|
| dump (Path A) or GETs (Path B: ~4–5k post panels at 2/s, cached) | me, owner's go for A | 1–2 h | 0 |
| Path B only: re-ask story pairs with frozen guides (~3 windows × ~1.2k pairs × 1.5 asks ≈ 5.4k questions, ~$0.0003 each, as connect's ~$0.25 / 850) | worker / script | 1–2 h | ≈ $2 |
| `shown=core` one-time re-ask (D only; join + merge + connect inputs of the 3 windows, ≈ 6–8k questions) | worker | 2–3 h | ≈ $2–3 |
| harness + `grouping.py` prototype + order/stability tests (scratch, private) | one agent | 1–1.5 days | — |
| sweep on dev (≈ 7k settings × 4 arms, pure functions) | script | < 30 min | 0 |
| time and memory runs (dump copy + `prep_scale`, 5 runs each arm) | script on the test Postgres | 1–2 h | 0 |
| blind labels: ~400 distinct rows + ~1,800 pairs (H1, H2) × 2 labellers + ties (~15%) | Claude subagents | 0.5 day | ≈ $30–60 in subagent tokens (~3k tokens a row, ~1k a pair) |
| analysis, results, breakage report | me | 0.5 day | — |
| waiting for H2 (7 fresh days after freezing) | calendar | 7 days | — |

**Total**:
- about 3 working days of agent time, plus the 7-day wait for H2;
- under $70: mostly labelling; Haiku is ≈ $2–5;
- no server writes, no migration, nothing deployed.

H1's results can be reported after ~3 days. The decision waits for H2.

## Case added 2026-11-16: one release, six rows (production)

A lab's flagship model ("Orbit-Max") over six days, as the reader's News showed it (names invented; real ids in
plan/research/0217-cases.md):
- day 0: a preview opens on the API → **two rows**: the lab's own "it is coming" post with two forum shares, and a
  6-voice preview row (forum, three channels, an aggregator).
- day 5: the official launch → **four rows**: the lab's announcement thread with 9 voices; an evaluator's
  benchmark thread ("+9 points", 2 voices: the evaluator and the lab quoting it); a model router's "live, $1.50/M"
  thread (2 voices: the router and the lab); a channel's "official and independent benchmarks" (2 voices).
Each small row is its own rule story (a thread or a judged pair) and no judged connection joins it to the launch row,
so v10.18's rule (a join needs a judged connection) keeps them apart. Rows sharing the exact main thing (the same
model version) and a release-family event type (preview, launch, availability, benchmark of it) within a few days
are what the reader calls "the same news". The core check must decide: one row with sub-lines (availability,
benchmarks, breakdowns) and the preview as an earlier stage, or separate rows linked as developments. Expected
check case: the launch day shows ONE row for the model, with the router and the benchmark as lines in it.

**Owner's decision (2026-11-16):** a preview is the same launch. Everything about one release of one exact thing
(rumour/teaser, preview, official launch, availability on platforms, benchmarks, breakdowns) is ONE row, with the
stages and the smaller stories as lines inside it, across the days it spans. Expected check case for the case above:
one row for the model from day 0 to day 5. The core check still keeps out stories that only mention the thing.

## Part 2 (owner 2026-11-16): an updated row comes back

Today the reader's read state is per post; a row that gains posts neither says so nor moves back up, and the tags
shown on rows (NEW / SAME / CHANGED) compare Mark X with Mark IX, which means nothing to the reader.
Build, on top of Part 1's one-row-per-release:
1. **Seen per row:** when the reader last opened a row (deepen 0154's seen state, built for tracks in v10.18; no
   parallel store), keyed by the row's stable identity across rebuilds.
2. **A meaningful update:** a new stage (teaser → preview → launch), new numbers (price, benchmark, size), a new
   independent source (not a repost or a copy of a voice already in the row), a correction or denial. Plain
   repetition does not count. Judged from stored readings (ent-v5 event type/origin, numbers) first, the worker only
   where unsure.
3. **The row comes back:** a row the reader has seen that gains a meaningful update returns to the top of News as
   "Updated: <what> · +N sources", its new lines marked; a row never seen is "New". The Mark X-vs-Mark IX tags leave
   the reader's News (they stay on /markx).
Measure blind on replayed days (the case above: preview read on day 0 → launch on day 5 must come back; the router
and benchmark lines on day 5 join the same update or come back once more if the row was opened in between; 20
reposts must not bring it back): precision of "Updated" (a labeller agrees something meaningful happened) ≥ 90%
(Wilson lower bound), returns per row per day ≤ 2, and no meaningful update missed on the labelled set.
