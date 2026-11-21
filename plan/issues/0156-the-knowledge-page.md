# 0156 — The knowledge page: what INSIGHT knows about one subject, built from claims and events

Status: **spec, after 0152 and 0153; adopted after 0161 E6** (2026-11-10). Fusion stage 7 (Pages). Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: 0152 (claims), 0153 (events), 0154 (seen state); the entity page (0119 A3, 0144's person page), the
track page (0145); 0095 (numbers over time), 0097 (where sources disagree), 0100 (study pages); `post_notes`,
`post_highlights` (stored today, shown on no page).

**Constraints:** no line without its claim; keep everything; no real names in committed files; realdata-check once
at release.

## Why
- The owner: news should be "used to create knowledge, not just read and forget".
- A page of this shape was built by Haiku from stored facts about one organisation: timeline, numbers, unconfirmed
  claims, disagreements, what changed. **37 of 62 lines were supported, 46 of 62 after fixes** (rough: private
  `plan/research/fusion/out/F8d`). Every error traced to the facts under it: a quoted person's words stored as the
  source's own; a post's date used as the event's date; a number without its basis. 0152 stores those three.
- A study page written from posts alone was 67% supported: it needs definitions the posts do not contain. So this
  page says only what the archive says, and marks what it does not know.

## What it does
### 1. A page per subject
An entity (an organisation, a person, a product and its versions), a track, or a chain of events. It is a new tab
on the pages that exist ("Knowledge"), not a new kind of page.

### 2. Sections, each a query (no model unless said)
1. **Now** — three or four lines on where the subject stands. **Written by one `page` call** from the subject's
   newest claims and events; each line carries the claim ids it rests on; a line whose ids are missing or whose
   numbers and dates differ from its claims' is dropped by code.
2. **Timeline** — events by **event date** (not post date), newest first, each folded: its card, its state, its
   sources, its posts by relation. An event with no date sits under the day its first post arrived, marked
   "date not given".
3. **Numbers** — claims with a number, grouped by metric and **basis**; a series when the same metric and basis
   repeat; each value with its date, scope and source. Different bases are never put on one line.
4. **Unconfirmed** — claims with status rumour, or reported by one origin only (0157 B), or asserted by a quoted
   speaker; each with what is known about it since (a later claim on the same event with status official or
   denied, linked by code).
5. **Where sources differ** — only what code can show: two claims on one event with the same metric and basis and
   different values, or different event dates. No judged "contradiction".
6. **New since you last looked** (0154).
7. **Your notes** — a note or a highlight attached to a claim or a post of this subject (`post_notes`,
   `post_highlights` gain a claim reference); shown here and on the post.
8. **Not in your archive** — one line when a section is empty ("no numbers stored for this subject").

### 3. How it stays right
- Every line opens its claims; every claim opens its quote in the post (0152's check).
- A claim labelled ✗ leaves the page at once and its lines are rewritten at the next run.
- The `page` call is repeated only when the subject's claims changed since (a hash of their ids).

### 4. Export
- The page as Markdown with its citations (addresses of the posts), from the page's menu.

## Measure
E6 (0161): five subjects in three spheres; every line read against its claims and posts by two blind labellers.

## What the results should be
- 90% of lines supported by their posts; 0 numbers or dates on the page that differ from their claims (by code).
- Opening a subject answers "where does this stand, what happened, what are the numbers, what is not confirmed"
  without opening a post.

## Done when
- Tests: each section's query on fixtures; a Now line with a missing claim dropped; bases never mixed; "differ"
  only on same metric and basis; a ✗ claim leaves; notes attach; export.
- The `page` schema, validation, the fake-claude test; frontend builds; vitest; design docs.
- On a local copy: five subjects' pages, read line by line (right, wrong, missed, exact rows, private).

## Measured (E6, 2026-11-20; private: `plan/research/fusion/measure/x1120/E6/`)
Five subjects (two organisations, two models, a person) from the server by GET, claims by claims-v1 (942 of 946 quotes found), pages per section 2.
- **Lines supported 112 of 128 = 88% (81-92): under the 90% bar.** By section: Now 75%, Timeline 93%, Numbers 81%, Unconfirmed 93%. No line was unsupported; the 16 misses are "partly". The two checkers agreed poorly (raw 63% and 73%), so the number is soft.
- **Numbers or dates differing from their claims (code): 0. Met.** A claim's own wrong event date still passes this check.
- Where sources differ: empty on all five pages (not exercised).
- **Cause of "partly":** a quoted person's words shown as fact, and narrowed scope dropped ("all users" for one plan's users). **Fix before re-measuring:** every Now and Numbers line carries its claim's speaker and status ("X says", "reported"), and its scope.
- Posts must be chosen as those naming the subject (the story's posts that never name it gave empty pages).
