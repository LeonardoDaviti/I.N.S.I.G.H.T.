# 0275 — Questions with citations (Stalker feature 6; builds 0098)

Status: **built (Stealth v10.33), switch `search.answers` OFF: the held-out measure is 94.7%, under the 95% bar.**
Written and built 2026-11-21.

## What
The reader asks in words on the search page ("what runs a 27B model under $1,500?") and gets an answer built only
from their own posts: every sentence with superscripts to the posts it rests on, the cited posts listed under it,
"Not in your sources" when the posts can't answer.

## How (built)
- **Retrieval, no model** (`markx/questions.gather`): the search page's own best-order ranking for the question (the
  hybrid search, words + meaning, `db/repo_search` + `markx/search.meaning_posts`, first 10), the entities the
  question names (`search.entity_cards`, up to 2) with each one's posts (`entity_brief.report_posts`: its own and its
  maker's first, 4 each) and, when an entity has a shown brief (`entity_brief.view`), up to 6 of its lines as NOTES
  naming their posts. Search's and the entities' posts take turns, 16 posts at most, each source, date, title and its
  first 1,200 characters (markx text v1).
- **The answer**: one `question` task a question (guide `question-v1`, schema `QUESTION_SCHEMA`: `answerable` and up to
  6 sentences, each with `cites`), asked of the worker like every Haiku question. The guide forbids outside knowledge,
  ranking words no post uses ("latest", "main"), describing a source beyond its byline, commentary on the posts, and
  linking facts a post gives separately.
- **Async**: `POST /api/markx/questions {q}` gathers, stores the `mx_questions` row (the question, its task, the posts
  in their numbers' order; migration 0170) and queues the task (priority -1); `GET /api/markx/questions/{id}` is the
  view the page polls every 4 s while `status` is `waiting`. The worker leases `question` first (`DEFAULT_KINDS`), one
  a call. **Latency** = the wait for the loop's next lease of the kind (the loop runs back to back; up to one cycle) +
  one Haiku call: **4–14 s a call, median ~10 s** (measured below, claude -p haiku), plus **retrieval 0.8–4.9 s,
  median ~3 s** (mostly the meaning scan; peak RSS of the measuring process 85 MB). The same question with the same
  posts is the same task: no second call.
- **The check in code** (`questions.kept`): a sentence is shown only with at least one cite inside the posts it was
  given (others removed) and only when every figure it gives is in a post it cites (`validate.missing_figures`, the
  briefs' rule); the rest are dropped and counted (`dropped`). Nothing kept, or `answerable` false: "Not in your
  sources". Nothing found to answer from: no task, "Not in your sources" at once.
- **UI** (plain): on the search page, while Mark X and `search.answers` are on, a hairline box above the entity cards
  and results: "Ask your posts this question" (asks the search field's words), then "Reading your posts…", then the
  answer with superscripts and the numbered cited posts (each opens the post), or "Not in your sources".
- Switch: `entity_bands.json` `search.answers` (off); off, the routes are 404 except `/questions/on`, and the page
  shows no box. Consumer feature `questions` (consumers.py), on: tasks are only ever made by the reader's tap.

## Measure (2026-11-21, the 11-19 server copy, read-only; Haiku via claude -p as the worker asks it)
Files: `plan/research/0275-questions/` (set.json, heldout.json, gather.py, answer.py, judge.py, the answers and the
judged rows; real data, gitignored). Judge: a blind `claude -p --model haiku` per kept sentence, seeing only the
sentence and the posts it cites ("every fact stated in the posts?"); for each "not in your sources", every post the
question showed ("does any answer it?").

| set | questions | sentences kept | supported | dropped by code | "not in your sources" right |
|---|---|---|---|---|---|
| tuning, guide draft 1 | 25 | 88 | 73 = 83.0% | 1 | 7/7 |
| tuning, guide as built | 25 | 90 | 86 = **95.6%** | 2 | 6/6 |
| **held out** (25 new questions, guide frozen) | 25 | 94 | 89 = **94.7%** | 2 | 6/7 |

**Bar 95% on supported sentences: held out fails by one sentence (90/94 would pass). Switch stays off.**

What the unsupported held-out sentences got wrong (rows in `heldout-judged.json`):
- attribution in reposts and quotes: a claim of OpenAI's given to Fortune (the article that reported it); a partnership
  turned around (BTC's partnership with Starlink said as Starlink's with BTC);
- a name the post doesn't use: "Starship" for a post saying only "the next launch"; "Hy4 flash" for a Tencent post
  naming the model only by its size (the judge's strictest call);
- an "update" paragraph read as the article's claim (the July 25 return to flight; the judge may be wrong here).
- "not in your sources" wrong once: "What does Colette Kress say about data center revenue?" — post 1 states data
  center income up 110% to $107.6 billion in Kress's earnings announcement; Haiku said not answerable.

Tuning-set misses fixed by the guide (draft 1 -> built): ranking words no post used ("the latest flight", "the main
launch this month", "the most recent release"), sources described beyond their byline ("a developer", "per a Fortune
report"), commentary ("this is build infrastructure, not a user feature"), dropped qualifiers ("most of"), and facts
linked that the post gave separately ("including").

Not measured: entity-brief NOTES (no entity brief exists in the 11-19 copy: built v10.31); production questions on
today's posts (the copy is two days old). The three questions the owner named: "GrapheneOS this month" is "not in
your sources" (the judge agreed: the copy's posts don't answer it); "Code Mode" was "not in your sources" under draft 1
and 4 sentences, all supported, under the built guide; "27B under $1,500" answered from @AZisk's Kadas Mind Pro
review (4 sentences, all supported).

## Next (to pass the bar)
1. Attribution: show each post's byline as "@author (shared by <feed>)" already does; add the quoted/linked
   publisher when a post is a write-up of another's claim (the post's own words vs the article it quotes), so "who
   says it" is in the input, not inferred.
2. "Not in your sources" recall: answer partial questions (the Kress miss) — a guide line that an answer to part of
   the question is an answer.
3. Re-measure on a new held-out set from production posts (the copy plus production GETs), then switch on at 95%.
