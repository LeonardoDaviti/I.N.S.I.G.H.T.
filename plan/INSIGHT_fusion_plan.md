# INSIGHT Fusion: the factory (the version after Stalker, and the production release)

Status: **roadmap, draft 1** (2026-11-10). Specs: 0149–0161. Nothing here is built. Evidence: two nights of Haiku
exploration (private: `plan/research/fusion/README.md`), all of it **rough** — one Haiku agent per experiment,
checking its own work on about 20 items, no second labeller, no held-out set. Every number below marked "rough" is a
reason to measure, never a reason to adopt.

The owner (2026-11-10): Fusion is "our exit on production"; it should make INSIGHT the place where "every news [is]
captured, analyzed and used to create knowledge, not just read and forget"; valuable information is produced "at
start when post is read"; Stalker is not built, so Fusion may redesign what Stalker planned. The always-on worker is
set aside for now: every spec here works with the worker started by hand, in batches.

## What INSIGHT is
A factory that turns a stream of posts into a memory you can read, ask and build on. Each stage makes one thing
from the stage before it, stores it, and cites what it was made from.

| # | Stage | It makes | Today (v10.13.1) | Fusion adds |
|---|---|---|---|---|
| 1 | **Capture** | posts from sources | feeds, page watching, the finder, the doctor, archives | every source checked and test-read when added (0149) |
| 2 | **Read** | a reading per post | kind, main event, entities, at 1,500–6,000 characters; about 13% of spend gives no stored answer (rough) | no wasted calls, long posts read whole (0150); types that fit any sphere (0151) |
| 3 | **Claims** | what each post says | none | claims with speaker, date, number and its basis, each with its quote (0152) |
| 4 | **Events** | one thing per happening | stories: link rules, then judged pairs inside 72 hours | an event with a key, a card, a date and a state; posts and claims attach to it (0153) |
| 5 | **Subjects** | what events are about | entities with identity; tracks; voices; series | unchanged; tracks suggested (0160) |
| 6 | **Measures** | counts over claims and events | surges at 3 voices a day; source signals | what a post adds, who confirms independently (0157); what a source adds, coverage (0158); surges against a subject's own past (0159) |
| 7 | **Pages** | what you read | News, entity pages, track pages, search | the knowledge page (0156); new since you last looked (0154) |
| 8 | **Answers** | your labels, back into every stage | label buttons on six different pages | one queue, the most useful question first (0155) |

**Why this order of stages.** Today the stored unit is the post, so everything above it (a timeline, a number over
time, "what changed", a digest) has to re-read posts or guess. With claims and events stored once at read time, each
of those becomes a query, is shared by every user of a hosted INSIGHT, and can be checked line by line against its
quote.

## Rules of the factory (unchanged from Shadow and Stealth, stated once)
1. **Rules where there is structure, reading where there is meaning.** Links, feeds, dates, series and identity keys
   stay code. Meaning (what happened, whether two posts tell one happening, whether a source fits) is read.
2. **Read once, at the start, and store it.** No view calls a model to re-read a post.
3. **Every line cites its post and its quote.** A claim whose quote is not in the post is refused by code.
4. **Shadow first.** Each new stage runs beside the old one, behind a switch, default off, until its held-out
   measure passes its bar (0161). Mark IX and today's Mark X are only read by it.
5. **Keep everything.** A replaced row is closed, never deleted.
6. **Measured, or not claimed.** A frozen guide, then an unseen set, two blind labellers, the owner's spot check.

## The specs

| Issue | Stage | What | Ready to build? | Its measure |
|---|---|---|---|---|
| 0149 | 1 | Source check at add: class labels by rule, a test-read, why the finder found nothing | rule and reasons: yes; test-read: after E8 | E8 |
| 0150 | 2 | Reading that wastes nothing: invalid answers re-asked alone, what may share a call, long posts in windows | waste and call rules: yes; windows: after E5 | E5 |
| 0151 | 2 | Types that fit any sphere | after E3 | E3 |
| 0152 | 3 | Claims at read time | storage and the quote check: yes; the guide: after E2 | E2 |
| 0153 | 4 | Events with a key | after E1 | E1 |
| 0154 | 7 | Seen state; new since you last looked (realises 0094) | yes, on stories, entities and tracks today | counts on the server copy |
| 0155 | 8 | One answer queue | yes | labels a day, before and after |
| 0156 | 7 | The knowledge page | after 0152 and 0153 | E6 |
| 0157 | 6 | What a post adds; independent confirmation | after 0152; the judge after E4 | E4 |
| 0158 | 6 | What a source adds (realises 0093); a digest by coverage (realises 0096) | counts after 0152 and 0153; the digest after E6's writer | on the server copy |
| 0159 | 6 | Surges against a subject's own past | yes (no model; the lab's labelled surges) | on the lab's sets |
| 0160 | 5 | Track suggestions (0101 part 3) | after E7 | E7 |
| 0161 | — | The measurements E1–E8 | run first | — |

## Order

**Step 0. Build now (no experiment needed; no guide changes).**
0150 A–B (waste, call rules) → 0149 A, C (class labels, finder reasons) → 0155 (the queue) → 0154 (seen state) →
0159 (surges). Each is small, deterministic, and makes the later measurements cheaper or the owner's labels more
frequent.

**Step 1. Measure (0161).** In this order: E1 events, E2 claims, E3 types, E8 test-read, E5 windows; then E4, E6, E7
once claims exist on a set. E1 first: the knowledge page, "new since" and novelty all stand on events, and E1 is the
least verified strong result.

**Step 2. The base, in Shadow.** 0152 claims and 0153 events (and 0151, 0150 C if they pass), reading the last 30
days first, newest first, then history in pages as today's backfills do.

**Step 3. Views.** 0157 → 0156 → 0158 → 0160, each behind its switch, each with label buttons.

**Step 4. Production's first hour.** Paste one source → INSIGHT proposes the sphere's sources, each test-read with a
one-line verdict (0149, 0148's scout) → the first worker run gives events, and tracks to choose (0160) → a page per
sphere made of what the sphere has: happenings where sources share them, tools and launches where they don't (the
3D sphere: 1 shared happening in 61, rough).

## What Stalker planned, and where it lands
Stalker's plan (`INSIGHT_mark_x_stalker_plan.md`) lists features over a graph. In Fusion each is a view over claims
and events, so none needs its own extraction.

| Stalker's feature | In Fusion |
|---|---|
| The timeline graph (0091), entity timelines | events by event date on the knowledge page (0153, 0156); the first edges (0131) stay |
| Numbers over time (0095) | a claim's number, with its basis and date (0152, 0156) |
| Source track record (0118) | what a source adds: first, alone, repeated (0158). Rumours confirmed or wrong: only once an event's state is measured (0153) |
| Claims and disputes (0097) | claims (0152). Disputes: **not as a judged feature** — contradictions were unreliable in every run; only two stored numbers with the same basis that differ (0156) |
| Questions with citations (0098, 0141) | asked over claims and events instead of post text; 0141's spec stands, its retrieval gains two tables |
| Noise per source (0093) | 0158 |
| Since you last looked (0094), weekly what changed (0096) | 0154, 0158 |
| Reports written by INSIGHT (0142), lasting importance (0146) | after Fusion's base; both read claims and events |

## Not in Fusion (measured, rough, and closed until new evidence)
- Skipping posts unread from their title and first words.
- An interest profile from what the owner opens (153 opened posts: too few).
- Forecasts scored for who was right.
- Study pages from posts alone (67% of lines supported: they need definitions the posts don't contain).
- Contradictions judged by a model.

## Open, the owner's
- **The worker.** Set aside (2026-11-10). What it costs to leave it: claims and events exist only after a run, so
  "new since you last looked" and the first hour wait for one. Reading costs about $1.38 per 1,000 posts today;
  Fusion's stages add about $2 (rough), nearly all shared between users.
- **What an event replaces.** 0153 runs beside Mark X's stories. Whether News is later made of events is decided on
  E1's numbers, not before.
- Older decisions still open: the ent-v4 guide, the three Stalker experiments, 0087's fine-tuning analysis.

## Two corrections to the exploration's own claims
- "Link rules found 2 multi-source stories, events found 19" compared events with **Mark IX's link rules only**.
  The test instance ran no worker, so Mark X's own joins (nearest posts by vector, then a judge: 0086) were never
  run on those spheres. E1 therefore has three arms, and the honest question is what events add **over today's
  Mark X**, not over links.
- "Nothing comes out of INSIGHT" was too strong: `post_notes` and `post_highlights` tables exist. No page of the
  reader uses them today (searched the routers and pages); 0156 gives them a place.

## E1, measured (2026-11-10): what it changes in this plan
On 375 unseen posts in four spheres and three languages, against two blind labellers: link rules joined nothing;
today's Mark X joined 33% of the pairs the labellers agreed on, events 39%; both were right on what they joined
(100%, 96%). Details: 0153 "Measured".
- **Stage 4 changes.** Fusion does not add an event join. Mark X's stories are the join in every sphere; they gain a
  key, a card, a date and a state. The work moves to what both miss: chains of acts, follow-ups inside one source,
  and candidates that are not typed for AI news.
- **Step 4 (the first hour) gets simpler:** a new sphere's news needs a worker run on its posts, not a new method.
- 0156, 0157 and 0158 read "event" as "a Mark X story with its key" until the chain step is measured.

## One list, with 0246 (2026-11-22)
0246 ("the full potential of our data", on the v10.26+ branches) and this plan describe the same work from two sides:
0246 from the stored assets, this plan from the stages. Merged, with every measurement to date (2026-11-10, -20, -22).

**Built since this plan was written (other sessions):** story chains (0219, a happening's steps linked), one release
one row (0236, on), entity relations (on, 2026-11-20), the general track briefer (0245/0249, on in v10.28), seen state
for tracks (0249's quick look).

| # | What | Issue | State | Next |
|---|---|---|---|---|
| 1 | **Claims at read time**, long posts in windows | 0152, 0150 C | claims-v2 passed (97.8% in post, dates 93%); windows passed; the stored reading holds only 22% of claims, so claims are their own task | **build** (Shadow-free: it passed); quarter dates and the status check in v3 |
| 2 | **The track briefer fixed** | 0245/0249 | on in production, failing: points supported 56% on the server's issues (bar 97%), cross-post joins 53% | fix the joins and digest-v3's hedge rule; re-measure on the same sets |
| 3 | Types for any sphere | 0151 | passed in six spheres; AI news 1.3 points under | one guide line (product vs object), re-check 30 AI posts; ship |
| 4 | Track suggestions | 0160 | passed (11/15; new spheres 5/5, 4/5) | fix the single-story gate, then build |
| 5 | Still referenced (lasting importance) | 0146 | 85% held out (a>=5, b>=4 other sources), no model | spec; exclude saved pages; fresh set |
| 6 | Who said what first: "also said by", origins by named speaker, source cards | 0157, 0158 A | hiding repeats failed twice (82-93%; 3-8% hide new facts); counts work | build the marks and cards, never folding; needs 1 |
| 7 | Source check at add | 0149 | fit passed; reading quality needs the page comparison | build A and C, B for fit only |
| 8 | The knowledge page | 0156 | failed twice (88%, 84%) with model-written lines | lines assembled by code from claims; re-measure; needs 1 |
| 9 | Since you looked across News and tracks; weekly digest | 0154, 0158 B | partly built for tracks | after 1 and 6 |
| 10 | Numbers over time, questions with citations, search by meaning | 0095, 0098/0141, 0247 | not started; 0247 skipped by the owner | after 1 |
Closed: 0153 (events as a separate join), 0155 (answer queue), 0159 (surges against own past).
