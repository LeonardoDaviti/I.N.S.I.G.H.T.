# 0157 — What a post adds, and who confirms independently

Status: **spec, after 0152 and 0153** (2026-11-10). Part A's judge is adopted after 0161 E4; part B is code. Fusion
stage 6 (Measures). Roadmap: `plan/INSIGHT_fusion_plan.md`.

Read first: 0152, 0153; 0120 (perspectives: what each source adds, inside a story), 0127 (duplicates folded), 0132 A
(voices: one voice, its channels), 0125 (`post_refs`: the links a post gives and their reasons).

**The idea, plainly.** A post is worth what it tells you that you did not already have. And a claim repeated by five
sources that all took it from one place has been said once.

## Why (rough: private `plan/research/fusion/out/F2d`, `F3b`)
- In later posts of a story, **43% of claims had already been said** by an earlier post of the same story.
- Judging a whole post "new or not" against similar earlier posts was unreliable; judging **claim by claim against
  the event's earlier claims** was what worked.
- Cost: about $1.18 per 1,000 posts if asked of every post — the dearest stage, so it is asked only where there is
  something earlier to compare with.
- A wrongly hidden new fact is the costly error; a repeat shown as new is cheap. The bar is set on the first.

## What it does
### A. What this adds (a judge over claims)
- **When:** a post attached to an event (0153) that already has claims from other posts.
- **Task `adds`** (guide `adds-v1`): the post's claims and the event's earlier claims (nearest by vector, at most
  20) → per claim: **new**, **repeats** (which earlier claim), or **updates** (which, and what changed: a number, a
  date, a status).
- **Stored** on the claim (`relation`, `to_claim`). Counted per post: adds N of M.
- **Shown:**
  - on the post page, "What this adds": its new and updating claims first; repeats folded under "already said by
    <source>, <date>", each opening the earlier quote;
  - on a News or event row, per member: "adds 3", "repeats";
  - a reading order "what adds most" on an event's posts (never the default feed order without the owner's say).
- **Never hidden.** A repeat is folded, one tap away (keep everything; the costly error stays visible).

### B. Independent confirmation (by code)
- **A claim's origin** is, in order: its `speaker` when the post quotes or relays someone; else the page the post
  links as its source (`post_refs` with a source reason, a quoted post, a repost); else the post's own voice
  (0132 A).
- **An event's claim is confirmed by N origins,** not N sources: claims that repeat each other (part A) are one
  claim; their distinct origins are counted. Five channels relaying one press release are one origin.
- **Shown** on the knowledge page's Unconfirmed section (0156: "one origin") and on an event ("3 sources, 1
  origin").
- Without part A (before E4 passes), origins are still computed per post and shown on the event.

## Measure
E4 (0161): 150 unseen later posts of events with earlier posts. Bar: a claim marked "repeats" really was said, 95%.

## What the results should be
- On a story's fifth post the reader sees the two lines that are new, not the whole post again.
- "Reported by 6 sources" stops meaning six witnesses when it is one.
- Expected size, from the 43%: a little under half of later posts' claims fold.

## Done when
- Tests: asked only with earlier claims; the three relations; folding never removes; origin by speaker, by link,
  by voice; origins counted over repeated claims; the fake-claude test.
- On a local copy: 30 events with 3+ posts — claims new / repeated / updated, origins against sources, 40 "repeats"
  read by the agent (exact rows, private).

## Measured (E4, 2026-11-20; private: `plan/research/fusion/measure/x1120/E4/`)
40 Mark X stories (216 posts) from the server by GET; claims by claims-v1; `adds-v1`, one post a call. Contested rows labelled by reading (the checkers disagreed on 56 of 160).
- **A: near miss.** "Repeats" really said: 56 of 60 = 93% (84-97), bar 95%. Repeats hiding a new fact: 2-4 of 60 (3-7%), bar under 3%. "New" really a repeat: about 3-5%. "Updates" really change something: 11 of 20.
- **The repeat share is about 20-24%, not 43%** (831 later-post claims: 19% repeats, 8% updates, 73% new).
- **B: works.** Of 97 claims said by two or more sources, 39 (40%) have fewer origins than sources; in 32 one origin. Origin assignment 17 of 20 right.
- Next: adds-v2 with "updates" defined as a changed number, date or status only, on a new set.
