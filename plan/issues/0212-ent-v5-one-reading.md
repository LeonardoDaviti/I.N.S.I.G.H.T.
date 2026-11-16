# 0212 — ent-v5: one reading of a post (read, read3, entities and cite in one call)

Status: **spec + feasibility measurement** (2026-11-16, branch `v1021-ent-v5-spec` from v1020 = v10.19). Nothing is
built into the pipeline. Draft guides: `plan/issues/0212-ent-v5-guide-draft.md` (d2) and `0212-ent-v5-guide-d3c.md` (d3c,
after the owner's decisions: see "Update: draft d3").
Private notes, scripts, inputs and every answer: `plan/research/ent-v5/` (gitignored: real posts).

**The owner (2026-11-16):** merge `read` (read-v2), `read3` (read-v3), `entities` (ent-v4.2, windows of 0176) and
`cite` (cite-v1) into one job. Only Haiku (never Sonnet). Fusion's rule (`plan/INSIGHT_fusion_plan.md`): read once
at the start and store it; claims (0152) are meant to come from this reading later, so v5 keeps a designed slot.

Read first: 0090 (mentions, identity), 0127 (read-v3), 0133 and 0133-v42-built (ent-v4.2, cite, the merge), 0150
(windows, re-asked items), 0152 (claims), 0176 (windows, fresh lane), 0191 (effort, prompt cache), 0201, 0210 (the
re-ask guard, v10.20).

## Update: draft d3 (2026-11-16, after the owner's decisions)
**The owner's decisions on d2:** aim the next draft at output and thinking tokens; `type_why` out unless it measurably
helps; effort low; more windows a call; target **v5 at or below today's cost per post, with an event type for every
post**. `cite` stays its own question for cue posts until v5's citations pass a bigger gold set. No claims in v5 yet.
No archive re-read: old rows stay (rollout step 4 is dropped).

**d3** (`plan/issues/0212-ent-v5-guide-d3c.md` is the one measured best, d3c): d1's text without the citations
section (27.7k characters; d2 was 34.4k), no null fields, no relations, one closing line asking for the JSON only.
Three variants measured: d3 (no `type_why`, `span` left out when it equals the name), d3b (no `type_why`, `span`
always), d3c (`type_why` back, `span` always). The schema's `citations` section is gone; `reading`, `event`,
`entities` and the `claims` slot stay as in 2.1.

### Measured (all Haiku 5.5 at low effort; read-v3's whole held-out test set, 464 posts, first windows)
| draft, call | $ / window | out / window (thinking) | event type | origin |
|---|---|---|---|---|
| read-v3 (frozen), its three stored runs | — | — | 71.5–73.4% (majority 73.7–74.0%) | 85.0–86.8% |
| d2 (with citations), 10 a call, 5m cache | 0.00087 | 1,475 (1,080) | 74.5% | 84.9% |
| d3, 20 a call, no cache | 0.00061 | 937 (642) | 74.7% | 83.1% |
| d3 + `type_why`, 20 a call | 0.00066 | 1,028 (719) | 75.2% | 84.6% |
| d3b, 10 a call, 5m cache | 0.00043 | 615 (278) | **69.0%** | **78.1%** |
| d3b, 20 a call, no cache | 0.00044 | 591 (274) | **70.4%** | **79.0%** |
| **d3c** (`type_why`, `span` always), 20 a call, no cache | **0.00054** | 797 (453) | **74.0%** | **80.9%** |

- **Thinking decides the reading's accuracy, and the guide's wording moves it.** d3b differs from d3 only in that the
  span is always written, yet Haiku thought 270–280 tokens a window instead of 640, and event type fell 4–6 points,
  origin 4–5. `type_why` costs 7% more and adds nothing when Haiku thinks enough (d3 vs d3 + type_why: 74.7 vs 75.2%),
  but **restores the event type when it thinks less** (d3b 69.0–70.4% → d3c 74.0%). It stays.
- **`span` left out when it equals the name** (d3): left out on 80–88% of entities, and then 3–6% of those names are
  not in the post, so the entry is refused (0213 would drop it): about 4% of the entities lost to save about 2% of the
  output. Dropped: `span` is always written.
- **Origin is 4–5 points under read-v3** in every d3 variant but the costliest (d3c 80.9% against 85.2–86.8%; d2 and
  d3 + type_why 84.6–84.9%). It is the one field d3c does not hold.
- **Cache and batch:** at 10 a call with the 5-minute cache the price per window is the lowest, but the thinking (and
  the accuracy) fell with it in both d3b runs; the no-cache 20-a-call runs are the measured ones above.

### The 60 sample posts (126 windows; cite kept as its own question: the old cite answer)
| run | $ / window | valid windows (first pass) | name Jaccard with ent-v4.2 (two ent-v4.2 runs: 0.58) | subjects the same (ent-v4.2 runs: 52%) | gold citations (25 posts) |
|---|---|---|---|---|---|
| d3, 10 a call, 5m | 0.00064 | 101/126 (span left out) | — | — | — |
| d3, 20 a call, off | 0.00083 | 110/126 (span left out) | — | — | — |
| d3b, 10 a call, 5m | 0.00046 | 116/126 | 0.591 | 48% | 75.8% (old 74.2%) |
| d3b, 10 a call, off | 0.00074 | 120/126 | 0.575 | 47% | 71.0% |

Blind labels on the names d3b and ent-v4.2 disagree on (three labellers, sides hidden, 70 a side): **v5 right 47/70 =
67% [56–77], ent-v4.2 right 39/70 = 56% [44–67]**: the entities hold with d3b's little thinking too (d2's: 71% / 49%).
The invalid windows are single spans or versions not in the post: under 0213 (v10.20) those entries are dropped and
the rest stored.

### Cost per 1,000 new posts (the sample's prices; 1.42 windows a post; `cite` on cue posts: 0.29 × $0.00086 = $0.25)
| | $ per 1,000 new posts | event type for |
|---|---|---|
| today: read + read3 (7% of posts) + entities + cite | **1.44** | 7% of posts |
| v5 d2 (citations inside) | 1.54–1.69 | every post |
| **v5 d3c + cite** (d3c's window priced at d3's sample price × 542/612, as its 464-post price is to d3's) | **≈ 1.29 (−10%)** | **every post** |
| v5 d3b + cite (10 a call, 5m) | 0.90 (−37%) | every post, 4–6 points less accurate |

**Verdict on d3:** the target is met by d3c (−10% per post, event type for every post at read-v3's accuracy,
entities as precise as ent-v4.2, citations unchanged because `cite` stays), **except origin** (−4 to −5 points).
Next: an origin fix (its rules moved next to `event`, or the hard cases trimmed to the origin ones that the misses
show) measured on the same 464, before the Shadow build. Haiku spent on d3: about $1.62.

## The answer in one paragraph (d2, before the decisions above)
One call reads one post (or one window of a long post) and returns `reading` (read-v3's fields), `event` (read-v2's
`main`), `citations` (cite-v1's list) and `entities` (ent-v4.2's list), with a reserved `claims` slot. One adapter,
in the module that writes readings and mentions today (`tasks.record`), turns it into exactly the rows the four kinds
write now, so no consumer changes except the places that pick a reading by guide id. **Measured on held-out posts,
draft d2 at low effort: entities as good as ent-v4.2 (agreement inside the noise; on the names the two disagree on,
v5's are right 71% against 49%), event type and origin as good as read-v3's on its whole held-out test set (458
posts: 74.5% against 71.8–73.1% for its single runs; origin 84.9% against 85.2–86.2%), kind better, answers valid on
95–99% of windows at the first pass, the post sent once instead of two to four times — but it is not cheaper at
today's mix (about +7% to +17% per 1,000 new posts), and its citation recall sits 3–6 points under today's pooled,
inside the old answers' own run-to-run spread, so citations are not passed yet.** What it buys is read-v3's event type and origin for every post (today 7%), citations in every window
(today the first only), 40% fewer calls and fewer than half the answers, and one place for claims.

## 1. Inventory: the four kinds today

### Fields, inputs, worker settings
| kind | guide (chars) | answer fields | input | per call | effort | prompt cache | planned for |
|---|---|---|---|---|---|---|---|
| `read` | read-v2 (2,523) | kind, events, main {headline_en, actors, object, action, date, numbers}, items [{headline_en, link}], mentions [{name, role}], lang | `post_block`: title, the first **1,500** characters, 12 links, the quote | 20 | Claude Code's default | off | every post in the reading window and the fresh lane |
| `read3` | read-v3 (13,413) | read-v2's + type_why, event_type (14), origin (maker / relay / other) | read's + `Address`, `Repost: written by`, `Published` lines | 5 | default | default (1-hour) | members of stories with 2+ members only (`folds.plan`) |
| `entities` | ent-v4.2 (14,786) | entities [{span, name, type, role, maker, by, family, version, variant, size, build}] ≤ 20, relations [{a, rel, b}] | the first **6,000** characters, 6 links; a long post a **window** each (0176: 6,000 with 200 shared, ≤ 12) | 20 (never two windows of one post) | medium | off | every post; the windows planner for older ones |
| `cite` | cite-v1 (7,015) | entities [{span, name, type: document / org / person, role: source / recommended / subject, by}] ≤ 30 | 6,000 characters, 12 links (first window only) | 10 | low | off | cue posts only (`ent42.cue`: 17–18% of posts) |

Each guide goes with its JSON schema appended (`system_for`): the worker's system prompt is 3.6k (read), 14.8k
(read3), 15.8k (entities) and 7.5k (cite) characters.

### What the logs say (the worker's own call log, `plan/research/markx-run-2026-11-07/log*.jsonl`)
The server's `GET /api/markx/overview` (`days`, `tokens`) was not read from this session (no access to the server
from here; nothing was written to it). The worker logs every call it answers, with Claude Code's own tokens and price
(Haiku 5.5: $0.10 / M in, $0.50 / M out), so the same spend is in its logs.

| since 0191's settings (14 Nov 01:45 – 16 Nov) | answers asked | valid | in / answer | out / answer (thinking) | $ / 1,000 valid | share of all spend |
|---|---|---|---|---|---|---|
| entities (ent-v4.2) | 76,647 | 62,349 (81%) | 2,432 | 1,493 (944) | 1.217 | **87.3%** ($75.85 of $86.90) |
| read | 2,428 | 1,101 | 319 | 194 (125) | 0.284 | 0.4% |
| cite | 616 | 361 | 1,672 | 552 (450) | 0.756 | 0.3% |
| read3 (no call since; the week before) | 11,912 | 10,662 | 1,539 | 935 | 0.675 | 1.2% of that week |

- Entities are 87% of the spend since the 0191 settings (the brief's ~92% is the same picture: the windows backfill
  of 0176 is almost all of it); reading in all is 88% now, 72% over the whole log.
- 19% of entities answers asked were not stored (invalid, missing or refused): paid and lost.
- **Per 1,000 new posts, today's mix** (0191's answers per new post: read 1.00, read3 0.07, entities 1.42, cite 0.29),
  priced at the logs: **$2.28** (entities 1.73, read 0.28, cite 0.22, read3 0.05).

### Who reads each field (the consumers; `markx/` unless said)
| field | read by |
|---|---|
| reading `kind` | `decide.World.kinds` (round-up gate), `tasks.reading_kinds` / `rule_card`, `anchors._wholes`, `units.split`, `news_rank` (Analysis needs `commentary`), `services/originals_service` (long reads), `source_stats` |
| `events` | `decide.World.events` (the two-event guard), `incremental` |
| `lang` | `translate.LANG_SQL` |
| `headline` / `main.headline_en`, `main.action/object/actors/numbers/date` | `search` (weights A, B), `event_types.from_reading` (happening group), `happening.key`, `finders` (numbers), `tasks.render_post` / `card_input` (judge, pair, card inputs), `services/discover_main_source` (named actors), `news.post_panel` |
| `items` | `units.split_reading`, `units._inputs` (round-up items) |
| `mentions` | `tasks.render_post` (judge inputs), `news.post_panel` |
| `event_type`, `origin` (read3) | `event_types.of_posts / types_of / typed_sql` → `folds` (duplicates fold), `built` (story type, leaks), `news_sections`, `significance` (kind of happening), `official` via `discover_main_source` |
| `type_why` | nobody |
| entity rows (`mx_mentions_now`: name, span, type, role, maker, by_name, family, version, variant, size, build, rule) | `pairing._subjects`, `candidates`, `back`, `news.entities`, `news_sections._entities` → `significance`, `surges`, `search`, `track_tools`, `person_page`, `timeline`, `entity_views`, `rename`, `identity` (and every identity query), `entity_addresses`, `entity_repair`, `entity_facts`, `perspectives.mentions_of`, `source_stats`, `utils/source_roles`, `happening`, `services/originals_service`; by `entity_id`: `graph`, `research`, `finders`, `entity_stage`, `later`, `scout`, `source_judge`, `news_rank`, `db/repo_source_discoveries` |
| entity `relations` | **nobody** (`tasks.record` never stores them) |
| cite entries | merged into the ent-v4.2 rows (`ent42.after_cite` / `main_mentions`, `rule = 'q2'`): every entity reader above; only `news.post_panel`, `api` (labels) and `ent42.labels_of / precision` tell q2 apart |

**Places that pick a reading by guide id** (where a new guide needs the one adapter of 2.3): `event_types.TYPE_GUIDES`
/ `GROUP_GUIDE`; `tasks.readings` and `reading_kinds` (default `read-v2`); `incremental.GUIDE`;
`happening.READING_GUIDE`; `units.READING_GUIDE`; `candidates.read_since` and `anchors._wholes` (literal
`'read-v2'`); `source_stats`, `discover_main_source` (`IN ('read-v2','read-v3')`); and four queries that take the
reading whose guide id sorts last (`ORDER BY guide DESC`: `news.post_panel`, `news_rank`, `translate`, `search`), which
would pick `read-v3` over `ent-v5` and breaks at `read-v10`. Entity guides are read through
`schemas.mention_guides()` (`ENTITY_ARMS`) and `mx_mention_sets`.

## 2. The merged answer

### 2.1 Shape (draft d2's order: the model writes `citations` before `entities`)
```json
{"reading":  {"kind", "events", "lang", "type_why", "event_type", "origin", "items": [], "mentions": []} | null,
 "event":    {"headline_en", "actors", "object", "action", "date", "numbers"} | null,
 "citations":[{"span", "name", "type": "document|org|person", "role": "source|recommended|subject", "by"?}],   ≤ 30
 "entities": [{"span", "name", "type", "role", "maker"?, "by"?, "family"?, "version"?, "variant"?, "size"?, "build"?}],   ≤ 20
 "claims":   null}
```
- `?`: left out when it has no value (the old schemas asked for every one as `null`: output tokens for nothing).
- **Dropped:** entity `relations` (no consumer stores or reads them). Kept out of the first version: `claims`.
- `reading` and `event` are null on a later window; code nulls them there whatever the model wrote (the smoke runs
  saw the model write one anyway).

### 2.2 Field for field
| v5 | old answer it becomes | old field |
|---|---|---|
| `reading.kind, events, items, mentions, lang` | read-v2 and read-v3 | the same names |
| `event` | read-v2 and read-v3 | `main` |
| `reading.type_why, event_type, origin` | read-v3 | the same names |
| `entities[]` (+ nulls for left-out fields) | ent-v4.2 | `entities[]`; `relations: []` |
| `citations[]` | cite-v1 | `entities[]` |
| `claims` | — | 0152's `mx_claims` rows, when a later version asks |

### 2.3 One adapter, in the module that owns readings and mentions (no parallel path)
- A new task kind `reading` (guide `ent-v5`, subject a post, one task per window as 0176), answered by the worker as
  any kind. `tasks.record` handles it in one branch that calls the code the four kinds call now:
  - window 0: `repo.add_reading(guide='ent-v5', kind, events, lang, headline=event.headline_en,
    reading=<the read-v3 shape: {kind, events, main: event, items, mentions, lang, type_why, event_type, origin}>)`
    — one `mx_readings` row a post, the shape every reader of `reading->...` already parses;
    then `_note_happening`, `_note_units`, as for `read`;
  - every window: `ent42.finish(entities, title, citations)` (own title dropped, `merge_cite`'s rules: a cite
    `subject` document skipped, a describing span skipped, a thing the entities typed as a model/product/... not made a
    document) → `repo.add_mentions(guide='ent-v5', win=w)` with the 0176 numbering and overlap rule. Both lists come
    in one answer, so the per-post advisory lock and the either-order merge of `ent42.after_cite` are not needed for
    v5 (they stay for stored ent-v4.2 rows).
- **Which reading a consumer reads** moves to one function, `readings.preferred()` (in the module that owns readings:
  `tasks.readings` today), with an ordered list `READING_GUIDES` = `("read-v3", "read-v2")` today and
  `("ent-v5", "read-v3", "read-v2")` after the switch, and a SQL helper for the queries. The 10 places listed in 1
  call it; the four `ORDER BY guide DESC` queries order by it. `event_types.TYPE_GUIDES` = the guides whose reading has
  `event_type` (`ent-v5`, `read-v3`). No reader parses the v5 answer itself.
- **Entities:** `ent-v5` joins `schemas.ENTITY_ARMS` (6,000 characters, rule off, its own schema), so
  `mention_guides()` and identity read its rows; `mx_mention_sets` decides the current set as today.
- **Shadow writes without moving anything:** in Shadow `repo.add_mentions(..., current=False)` stores the v5 mentions
  but leaves `mx_mention_sets` on the old guide (today a new guide's answer moves the set at once), and
  `READING_GUIDES` keeps v5 last. The switch moves both.

### 2.4 Validation (the old rules, carried over, per section)
| rule (from) | v5 |
|---|---|
| schema of each section (read-v3's enums, ≤ 12 items, lang pattern; ent-v4's types and roles; cite's types and roles; ≤ 20 entities, ≤ 30 citations) | the same schemas, nested |
| `main` null iff `events` none; headline ≤ 25 words (`validate._read`) | `event` null iff `reading.events` none; the same headline check |
| every entity `span` occurs in the post, folded (`validate.occurs`); `version` occurs (`version_occurs`); `recommended` only on a document (`_entities`) | the same, on `entities` |
| every citation `span` occurs; an org or a person is a `source` only (`_cite`) | the same, on `citations` |
| a later window: reading null | code sets it null |

`validate.check('reading', ...)` runs the adapter and then **each old kind's own check** on its part (as the
measurement did), so the rules stay in one place. **A failed section does not sink the others** (0150 A, 0152's quote
rule): the sections that pass are stored; the task is asked again alone, once, for the failed section's sake, and a
second failure stores nothing more for that section. Measured first-pass validity, d2: 95–98% of the sample's posts, 97.6–99.2% of its windows, 94.6% of the 464 first
windows (the old four together on the sample: 268/272 answers); most failures are one span or version not in the post,
which under one whole-answer rule would cost the reading and the event as well.

## 3. Long posts
- Windows exactly as 0176 (6,000 characters, 200 shared, at most `entity_windows_max`, 12): window 0's input is
  read-v3's head (address, repost author, published time) over the first 6,000 characters and 12 links; a later window
  is 0176's window input (head, `Window: k of n`, its text).
- **Which section from which window:** `reading` and `event` from window 0 only (the post's head and lede; a later
  window's are nulled by code). `entities` from every window (as today, numbered from w × 1000, a name wholly in the
  shared 200 characters counted in the window before). `citations` from **every** window (today: window 0 only; long
  papers keep their references at the end) — a change, measured below as "all windows".
- Never two windows of one post in one call (`split_calls`, 0150 B). Windows that are markup (0150 E5) are a later
  slice.
- The reading reads 6,000 characters where read-v2/v3 read 1,500. Measured effect: the post's `kind` is better (the
  blind labellers chose v5's kind 6–8 times, the old one 2–3, on the 11 disagreements); the event type is as good (6).

## 4. Prompt design for Haiku
- **Guide:** draft d2 = read-v3's text (kind, events, items, mentions, lang, type_why, the 14 event types, deciding
  rules, hard cases, origin), read-v2's `main` as `event`, cite-v1's body as `citations`, ent-v4.2's body as
  `entities`, word for word wherever the measured guides said it; 34.4k characters, 36.8k with the schema — against 41.7k for the four system prompts. d1 (29.5k) asked `citations` last and only for "what entities
  does not already list": its citation recall fell to 31–61% (three runs), so d2 asks the full cite list first.
- **Output size:** per window, d2 at low effort wrote 1,700–1,900 output tokens, of which 1,370–1,550 thinking
  (the old four: 3,590 a post, of which 2,321 thinking). Without thinking, the answer is about 350 tokens a window
  (the null fields and relations gone). Output is 75–80% of the price: **thinking is the cost lever**, not input.
- **Thinking effort:** low. Medium (d1) cost 42–52% more and was not better on any section (citation recall 53%, event
  type 65% on the 20 gold posts). `MAX_THINKING_TOKENS=0` does not turn thinking off under `claude -p --effort low`
  (measured: thinking unchanged), so effort is the only control the worker has.
- **Prompt cache:** 5-minute (`CLAUDE_CODE_PROMPT_CACHE_TTL=5m`), first call of a cycle alone (`Worker.warmed`), as
  0191 does for the one-item kinds: the fixed prompt (guide, schema and Claude Code's own part) is about 13k
  tokens a call (measured on one-item calls), more than half of a 10-window call's input. Measured on the same
  arm (d1 low): cache off, 5 a call $0.1255; 5m cache, 10 a call $0.0802–0.0863 (−31% to −36%). Claude Code writes the
  items' text into the cache too (at 1.25x), which no later call reads: the cache gains only on the guide.
- **Batching:** 10 windows a call (never two of one post). At 5 a call the guide alone is 2.6k input tokens a window.
- One `claude -p --model haiku` call, no tools (the worker's `claude_argv`), the worker's `HEAD` and `parse_lines`.

## 5. Rollout
1. **Build** (one slice, test-first): kind `reading` + guide `ent-v5` (frozen from the draft that passes 6); the
   adapter and validation of 2.3–2.4; `readings.preferred()` and the 10 call sites; `add_mentions(current=False)`;
   a switch `reading_guide` (mx_settings): `off` (default; nothing planned), `shadow`, `on`.
2. **Shadow** (`shadow`): `reading` planned for **new posts only** (the fresh lane), beside the four old kinds, which
   keep planning and stay what every consumer reads. The /markx Worker tab shows, per section, v5 against the old
   answers on the same posts (agreement and the labels of 6), and the cost per 1,000 posts of each.
3. **Switch** (`on`, the owner's decision, after 6 passes on held-out posts and a week of Shadow): `READING_GUIDES`
   and `mx_mention_sets` move to `ent-v5` for posts that have it; `read`, `read3`, `entities` and `cite` stop being
   planned for new posts. Every old answer and row stays (keep everything); a post read before the switch keeps its old
   rows as its current ones.
4. **The archive** is re-read only on the owner's decision, by the same planner over the reading window, held by
   the re-ask guard (0210, v10.20: a kind past 2,000 tasks a day held, asked last, priced on /markx). A whole re-read
   of the server's ~60k posts (≈ 85k windows) costs about **$95–105** at the sample's d2 price per window (long windows cost more in the logs).
5. Back: `on` → `shadow` or `off` puts the old guides first again (no row is rewritten).

## 6. Bars (per section; held-out posts; a field used automatically needs its point ≥ 97% and Wilson ≥ 90%)
| section | bar | measured here (d2, low effort) | verdict |
|---|---|---|---|
| entities | precision not below ent-v4.2's (lab 89–93% new-entity precise; all-entity 94–98.7%); names ~98% right (0090 v2) | name agreement with ent-v4.2 0.51–0.55 Jaccard against 0.58 between two ent-v4.2 runs; subjects the same 37–40% (two ent-v4.2 runs: 52%, n 25); on the names only one side gave, blind labels: **v5 right 50/70 = 71% [60–81], ent-v4.2 right 34/69 = 49% [38–61]** | at least as precise; recall not measured beyond agreement |
| citations | recall of gold documents and sources not below ent-v4.2 + cite (lab 75.6%) | gold, 25 posts (62 items): v5 61 / 68 / 60% (three runs) against 74% (one old run); 40 more cue posts (111 items): v5 47.7% (all windows 48.6%) against the stored production-config answers 48.6% and a second old run (default effort) 61.3% | inside the old answers' own spread (49–61% on the same 40 posts); pooled 3–6 points under; **not passed yet** |
| reading: kind, events | match read-v2 (lab kind 79.5%, events 90.8%) | v5 = read-v2: kind 78–81%, events 82–88% (read-v2 against its stored run: kind 89%, events 86%); gold (15): kind 73–80% vs 73%; blind labels on disagreements: kind v5 6–8, old 2–3; events even | passes (kind better) |
| reading: event type, origin | read-v3's (lab single run ~72%, 3-run majority 73.9%; origin 87.3%) | **read-v3's whole held-out test set (458 posts answered):** event type **74.5% [70.3–78.2]** against read-v3's three single runs 71.8 / 73.1 / 72.1% and their majority 73.8%; origin **84.9% [81.4–87.9]** against 85.2 / 85.4 / 86.2% (majority 87.1%). v5 agrees with a read-v3 run on 73.6% of types (two read-v3 runs: 80.8%): it differs as much as it is right. (On the sample's 20 gold posts v5 had 55–65% against 70%, and the labellers chose the old type 4–5 times against 1 on 7 disagreements: a 20-post subset's noise, which the 458 settle.) | passes: event type as good as read-v3's (a point better than its single runs), origin within a point |
| validity | first-pass valid ≥ the old kinds' (0191's lab: read 99.7%, entities at medium 98.1%, cite at low 94.9%) | 97.6–99.2% of the sample's windows; 94.6% of the 464 first windows (11 spans not in the post, 6 answers missing, 7 values outside a set); the old four fresh on the sample: 98.5% of answers | passes with section-level storage (2.4); a whole-answer rule would lose more than today |

Fields used automatically today (`event_type` by the fold, News sections, significance; `kind` by the round-up gate;
entities by identity) are held to the 97% / Wilson 90% bar **as precision against the gold of their own lab sets**
wherever the old guide was; where the old guide itself sits under it (event type 74%), the bar is "not below the old
guide on the same posts".

## 7. Cost per post (Haiku 5.5 list price; the sample's own calls)
On the 60 sample posts (they over-represent long and cited posts: 17 long, 26 cue; the server: 15% and 17%), each
call's price split over its items:

| | answers | calls | in tokens / post | out / post (thinking) | $ / post |
|---|---|---|---|---|---|
| old four (today's settings; read and read3 on every post, entities on every window, cite on the 26 cue posts) | 272 | 33 | 8,028 | 3,590 (2,321) | 0.00271 |
| v5 d2, low, 10 a call, 5m cache (two runs) | 126 | 20 | 7,695 | 3,625–4,008 (2,877–3,265) | 0.00228–0.00250 |
| v5 d1, low, 10 a call, 5m cache (two runs) | 126 | 20 | 7,154 | 1,834–1,944 | 0.00134–0.00144 |

**Per 1,000 new posts at the server's mix** (read 1.00, read3 0.07, entities 1.42, cite 0.29 answers a post; priced
at the sample's $ per answer of each kind):

| | $ per 1,000 new posts |
|---|---|
| today: the four kinds as planned (read3 on 7% of posts) | **1.44** (the logs price entities windows twice as high: $2.28) |
| today, if read3 were asked of every post (what v5 gives) | 2.14 |
| **v5 d2** (1.42 windows a post) | **1.54–1.69** (+7% to +17% against today; −21% to −28% against read3 for every post) |
| v5 d1 (citations weak) | 0.90–0.97 |

Why it does not save more: output is 75–80% of the price and it is mostly thinking, which one call does not share
much (d2 thinks 1,370–1,550 tokens a window against ent-v4.2's 470 at medium and read-v3's 720); and today's read3 and
cite are asked of a minority of posts. What it saves for sure: the post text and four guides sent once (input per
post −4% with the cache, 20 calls instead of 33, 126 answers instead of 272).

## Feasibility measurement (2026-11-16)
- **Sets** (all held out from the guides' own tuning; local copy `prep_mxreal` cloned to the scratch server, read
  only, dropped after): 60 posts = 25 of ent-v4.2's lab test/ordinary sets (gold documents and sources; 18 cue
  posts), 15 of read-v2's lab set (gold kind and events), 20 of read-v3's lab test set (gold event type and origin);
  126 windows. Plus 40 more cue posts of ent-v4.2's test set (117 windows) for citations, and read-v3's whole test set
  (464 posts, first windows) for the event type.
- **Old answers:** each old kind asked fresh at today's worker settings (`claude -p --model haiku`, the worker's own
  system prompt, prompt, parser, per-call size, effort and cache), plus the stored lab answers (0191's A/B runs,
  read-v3's three frozen runs) as the old-against-old noise.
- **Arms:** d1 low (cache off, 5 a call), d1 low (5m cache, 10 a call) ×2, d1 medium, d2 low ×3 (one of them asked
  with `MAX_THINKING_TOKENS=0`, which changed nothing), d2 low on the 40 cue posts and on the 464.
- **Blind labels** (two labellers on the 30 reading disagreements, verdicts the same on 23; three labellers on 140
  entity names one side gave and the other did not, 70 a side, sides hidden).
- **Haiku spent:** $1.52 at list price in the arms (1,735 answers asked in 246 calls), plus about $0.07 of smoke tests: about
  $1.6 in all, inside the $3 asked.

## Open questions for the owner
1. **Cost.** v5 does not lower the spend at today's mix (+7–17% per new post); it lowers it against "read-v3 for every
   post" (−21–28%) and asks 40% fewer calls. Is "one reading, event type for every post, citations in every window" worth that,
   or should the next draft aim at the thinking (the real cost) first?
2. **Event type for every post.** v5 gives read-v3's event type and origin to every post, where today only story
   members (7%) have them. The fold, News sections and significance read them through `event_types`: with more posts
   typed, their inputs change (more posts typed, none typed worse on the measure). A check of what changes on the
   News page belongs to the Shadow week.
3. **Citations.** d2's recall sits inside the old answers' spread but under the one old run on 25 posts. Keep `cite`
   as its own question on cue posts (17%) beside a v5 without the citations section (d1-shaped: $0.90–0.97 + cite's
   ≈ $0.25 = ≈ $1.2 per 1,000 posts, the cheapest measured shape), or accept d2 after a bigger gold set (the 90 test
   posts all at once)?
4. **Claims** (0152 E2: asked with the reading, claims halved and fell to 89% right). The slot stays empty in v5; a
   claims-v2 inside v5 needs its own measurement against claims asked alone.
5. **The archive:** re-read ~60k posts (≈ $95–105) after the switch, or keep the old rows for older posts?
6. **`type_why`** is read by nobody: keep it (it is written before the type and the lab measured it helping), or drop
   it to save ~20 output tokens a post?
