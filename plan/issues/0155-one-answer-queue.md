# 0155 — One answer queue: every question INSIGHT has for you in one place, the most useful first

Status: **spec** (2026-11-10). Fusion stage 8 (Answers). No model. Buildable now. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: 0086 F (`markx/labels.py`: the queue, the split, precision per feature), the entity review queue
(0119 A, `/entities/queue`), the label endpoints (`/labels`, `/labels/news`, `/labels/perspective`, `/labels/fact`,
`/labels/edge`, `/labels/back`, `/tracks/{id}/labels`, `/sources/stance/label`, a translation's and a mention's
label).

**Constraints:** keep everything (a changed answer is a new row); every existing label store and its meaning stay;
realdata-check once at release.

## Why
- Features wait on labels and do not get them. The owner's four tracks had no ✓ / ✗ on the day 0147 was measured,
  so their precision is unknown and a passive match cannot join by itself (0145 needs 20 labels and 90%).
- Questions live on about ten pages (the Mark X queue, the entity queue, each track, perspectives, facts, edges,
  back in the news, stance, translations, mentions). Nothing says which answer matters most today.
- Each question is asked in an order that suits its page (newest, or a hash). An answer's worth differs a lot: the
  20th label of a track turns auto-join on; the 300th label of a feature at 97% changes nothing.

## What it does
### 1. One page, "Questions"
- A daily set of **10** (a setting), drawn from every existing store through one reader interface; each kind keeps
  its own evidence view and its own buttons (same event / follow-up / different; right / wrong; ✓ / ✗), and writes
  to its own store exactly as its page does.
- One tap or one key answers and brings the next. "Skip" and "unsure" as today. The page shows how many are left
  today and what today's answers changed ("Track 'Local setups': 18 of 20 labels, 2 to go").

### 2. The order: what an answer is worth (by code)
Each waiting question gets a score, the product of three numbers, each shown on hover:
1. **How uncertain** INSIGHT is: closest to its bar first (a judge's confidence near the feature's threshold; a
   track item near its band's edge). A decision far from its bar scores low.
2. **How much depends on it:** rows that change if the answer is no (a story's members, an entity's posts, a
   merge's two sides, a track's waiting items in the same band).
3. **What it unlocks:** a feature or a track short of the labels its switch needs (0145's 20; a guide's bar with a
   wide interval) scores its remaining labels higher; a feature whose precision interval is already narrow scores
   lower.
- No kind takes more than 4 of the day's 10, so one busy feature cannot fill the page.
- The held-out split of 0086 F is untouched: a label keeps the split its item was given.

### 3. The pages keep their buttons
- Answering on a feature's own page removes the question from the queue. Nothing is asked twice.

### 4. What it reports
- Labels per day, per kind; each feature's precision and interval (as `/labels/precision` today) with the count
  still needed to reach its bar.

## What the results should be
- More labels where they decide something: after two weeks, every track with 20 labels or a stated count to go;
  no feature waiting on labels without the queue asking for them.
- Labels a day, before and after (the server's `mx_labels` and track labels by date, by GET).

## Done when
- Tests: one reader over every store; the three numbers and their product; the cap of 4; an answer on a feature's
  page leaves the queue; the split kept; each kind's write goes to its own endpoint's store.
- Frontend builds; vitest; keyboard answers; the design docs claim the page.
- The before / after count.
