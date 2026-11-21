# 0153 — Events with a key: one stored thing per happening, in any sphere and language

Status: **changed by E1 (2026-11-10): the separate event join is dropped; keys, cards, dates and state on Mark X's
stories stay, plus three additions (see "Measured")**. Not yet rewritten section by section. Fusion stage 4 (Events). Shadow, beside Mark X's stories. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: `plan/HANDOFF-v10.md`; 0086 E (`markx/decide.py`: Mark X's stories start from Mark IX's, then judged
joins); `markx/candidates.py` (the four candidate sources and their 72-hour windows); 0127 (duplicates folded), 0128
(an event type per story), 0131 (first edges), 0134 (series), 0091 (the timeline graph); 0152 (claims).

**Constraints:** Shadow: mx_* only, Mark X's stories and News untouched; keep everything; no real names in committed
files; realdata-check once at release.

## Why
- **A story today is a set of posts, with no identity of its own.** In the exploration the same launch sat under 2–4
  story ids, and one filing was 6 rows (rough: private `out/F4b`, `F5b`). A model asked to name an event's key did
  not keep keys stable between calls; **a pass that sees the open events did**, on one organisation (`F4d`, `F4e`).
- **Outside AI news the join is the problem.** In three new spheres, Mark IX's link rules formed 2 multi-source
  stories; reading each post for what happened and grouping by happening gave 19, 18 judged right, 10 of them
  across Georgian, Russian and English (rough: `F9aA–C`; the same agent grouped and judged, mostly on titles and
  first lines).
- **What that comparison did not include:** Mark X's own joins (nearest posts by vector, then a judge) were never
  run on those spheres. Its candidate rules are also built for AI news: the `entity` source needs a model, product,
  software, paper or dataset as the subject. E1 measures what events add over **today's Mark X**, which is the
  number that decides this issue.
- **Not every sphere has shared happenings.** The 3D graphics sphere had 1 in 61 posts: it connects by tool and
  product line. And a recurring subject (an annual report, a weekly figure) was grouped as one event when it is a
  series.

## What it does
### 1. An event
`mx_events`: an id, a **card** (one English sentence: who, what, when — the thing every member post is about), its
type (0151), its date and precision (from claims: 0152), a **state** (rumoured, announced, happened, denied), opened
and last-changed times, `valid_to`. `mx_event_posts`: a post, its relation (**tells it**, **develops it**, **reacts
to it**, **mentions it**), the call that said so.

### 2. A post finds its event
- For each read post whose reading has a main event:
  1. **Candidates, by code:** open events of the last 14 days nearest to the post (the stored vector against the
     cards' vectors; the card is embedded by the worker's embedder as names are), plus events sharing its subject
     entity by identity. At most 8.
  2. **One `event` task** (guide `event-v1`): the post's headline, its claims and the candidates' cards and dates →
     one of the candidates with a relation, or **new** with a card.
  3. **By code:** a new event is opened; a "develops" answer attaches the post and may move the state (announced →
     happened) with the claim that says so.
- A roundup attaches by its items (the reading's `items`), each as a mention, never as a whole.
- A post whose reading has no event attaches to none.

### 3. Guards
- **A recurring subject is a series, not an event:** an answer joining posts more than 14 days apart under one card
  needs the card to name one dated happening; otherwise the posts are offered to series (0134) and the event stays
  per occurrence.
- **The card must cover its members:** when an event reaches 5 posts, and then on each doubling, one check call
  reads the card against 5 random members' headlines; a member it does not describe is detached to a question in
  the queue (0155).
- Late posts: Mark X's late-post rule holds (a post more than 72 hours after the event opened needs "tells it" at
  the merge bar; otherwise it develops or reacts).

### 4. Beside stories, not instead
- Events are written in Shadow. A page on /markx lists them (card, state, posts by relation, languages, sources),
  with label buttons: right event, wrong event, should be with <another>.
- A Mark X story and an event are compared in the nightly run: same members, an event split over stories, a story
  holding two events. The counts are the evidence for the owner's later decision whether News is made of events.

## Measure
E1 (0161): three arms on the same unseen posts — Mark IX's links, today's Mark X, events — in four spheres and
three languages, grouped blind by two labellers who read the posts.

## What the results should be
- One key per real happening: 90% of the posts of a known happening under one event; an event's members all about
  its card 95%.
- Multi-source happenings in a non-AI sphere: at least twice what today's Mark X finds there, at no lower precision
  (if not, this issue shrinks to keys and state on top of Mark X's stories).
- On the owner's AI news: no story today's Mark X gets right is split.

## Done when
- Migration; candidates; the `event` schema and validation; opening, attaching, state changes; the two guards; the
  comparison with stories; the page with labels; the fake-claude test.
- On a local copy of each sphere used in E1: events per sphere, multi-source and cross-language counts, 30 events
  read by the agent with exact rows (right, wrong, missed), private.

## Measured (E1, 2026-11-10; private: `plan/research/fusion/measure/E1/REPORT.md`)
375 unseen posts (AI news; Georgian and Caucasus news in three languages; climate and energy; economy), grouped
blind by two Haiku labellers whose unit was a happening **with its next steps and reactions**. Pairs of posts:

| Arm | pairs joined | right | recall of the 130 pairs both labellers made |
|---|---|---|---|
| Mark IX's link rules | 0 | — | 0% |
| Today's Mark X (as shipped) | 43 | 43 (100%) | 33% |
| Events (sections 1–2 above, without the vector prefilter) | 56 | 54 (96%) | 39% |

- **The bar (precision 95%, recall 80%; outside AI news twice Mark X) is not met.** Outside AI news events joined 29
  of 92 agreed pairs, Mark X 33; either arm, 47.
- **So section 2's join is not built.** Mark X's stories stay the join. A new sphere gets its news from a worker
  run: Mark X formed 12 multi-source groups in the three non-AI spheres with nothing changed.
- **What both arms miss, and this issue now specifies instead** (each needs its own unseen set before adoption):
  1. **The chain:** a happening's next steps and reactions are separate acts to both arms (a memo about an affair;
     the hearing after a lawsuit). A step that links stories as "develops" / "reacts to", and a News row that shows
     the chain as one.
  2. **Same-source follow-ups:** 19 of Mark X's 59 misses outside AI. Its candidates never pair two posts of one
     source. Ask them, as "follows up", inside one source.
  3. **Candidates outside AI:** 27 of the 59 were never asked (the 8 nearest by vector at 0.65; the entity source
     found 4 candidates in 679 posts because its types are AI news's: 0151).
- **Still open, the owner's:** whether a News row should be the act or the chain. The labellers' unit was the
  guide's choice; the spot check (20 pairs) asks exactly this.
