# 0181 — Own round-ups: units, the attach relation, the issue's time, the digest (Stealth v10.16, slice K)

From the v10.16 architecture plan (section 4, "Own round-ups (Units)"); 0158 (a digest by coverage), 0166 (Pairing),
0180 (anchors). Names below are invented; the real rows are in the private notes
(`plan/research/roundups-1016/notes.md`).

## The problem

A round-up (a daily AI digest, a link list, a long newsletter) carries many items. It was judged as a whole, never
compared and never a follow-up, so its items were invisible to stories: a daily digest listing a release, a blog post
and a tweet INSIGHT already holds said nothing about them. Measured before: an item's links point at the item's own
stored post 14 times in 15. One digest source is stored at a fixed time each day although its items are from around
that day, so its date sat up to two days from what it reports.

## Built

### 1. `markx/units.py` (a deep module)

- **Unit** = (post, n, span, links, text, at): the n-th item of a round-up, its character span in the HTML read, the
  pages it links (normalized as posts are), its words, its time.
- **Splitters** (pure `split(html, text, url, reading, skip)`; the finest split is used):
  - `list`: each list item carrying a link of its own is an item; a list item with no link is in the nearest item
    around it, or, right after an item, its detail. A heading ends every list left open (digests leave `<li>` and
    `<ul>` unclosed; each next topic would else nest under the last and swallow the rest).
  - `sections`: headed sections carrying a link.
  - `lines`: when bullets open half the lines that link, a bulleted line starts an item and the lines after it
    continue it (a Telegram digest); else each line carrying a link is an item.
  - `reading`: a round-up the reading names whose HTML gives too few items: the reading's own items (headline, link),
    each placed on the line that links it.
  - No item links the post's own page (a table of contents) or its source's signature (`post_links.boilerplate`).
- **The tag**: the reading says `roundup` (and the post splits into 2+ items); or the post has a digest's shape (5+
  list items, sections or bulleted lines carrying links, to 4+ pages, holding half its words), its reading did not see
  it whole (a read task shows 1,500 characters), and its source is a digest source (more than half of its posts of
  150+ words have the shape). Plain paragraphs that link are never a shape (an essay's as often as a digest's); an
  essayist's post with a list of links has the shape but its source is no digest source.
- **Stored** (migration 0123): `mx_roundups` (one row a post the splitter looked at: tag, why, adapter, basis, issue
  time; kept current), `mx_units` (each split's items, appended when the split's inputs change: code, reading, text),
  `mx_attach` (unit → stored post, once per source). Nothing rewrites a post or deletes a row.
- **When**: a read-v2 reading landing (`tasks.record` → `units.note`, in a savepoint) and the candidates job's step
  (`jobs._units_step` → `units.backfill`: 1,000 posts never split by this code a run, newest first, then the
  round-ups of the last 3 days attached again, as a cited post may be stored after its digest; in a savepoint: a
  failure is logged and the candidates run stands). `counts.units` in the job's last result.

### 2. The issue's time, in one place

`pairing.post_date` (and `POST_DATE`, which back.py formats) reads a round-up's issue time: its latest attached item's
time within two days of its own date (`ISSUE_REACH`, either side: a daily dated at the start of the day it covers).
No attached item: its own date. `published_at` is never rewritten; `pairing.ordinary_date` is the old expression (what
the issue time is computed from). Every consumer of Pairing's post date gets it: the candidate sources' windows
(`Posts`), the centroid and entity sources, back and the anchors engine (`back._date`), the happening source and
backfill. The issue times are read once a query (an InitPlan over a partial index) and looked up per row: a correlated
lookup made the callers' window queries 3–6x slower (and switched JIT on); this form measured as fast as before
(below). An ordinary post's date is identical (tested on the seeded world, every caller).

### 3. Pairing's `attach` relation

A fourth policy row: sources `link`; a stored post whose address a unit links, dated from 14 days before the
round-up to 2 days after (a digest dated at its day's start cites that day's posts: 591 of 642 forward hits within 42
hours; the rest were an archive's issues stored under one date); never a round-up, never the round-up itself;
`independence` NEVER_VOICE (who wrote it never matters: an item is no voice); `units` = unit. `pairing.attaches` is the
gate, `pairing.attach_targets` the source; units.py stores it (never in `mx_candidates`, which the decision run reads).

**Stories show "also in round-ups"**: `units.also_in(cur, posts)` / `also_in_story`; the Mark X story view
(`GET /api/markx/stories/{id}`) gains `roundups` (the round-ups carrying a current member, members excluded), and the
story page a line "Also in round-ups: <source> (item n), …". The News row is not annotated (news.py is slice M's; to
add it later: one call `units.also_in(cur, [post ids of the row])` where news.view builds `items`, display only).

### 4. The digest (own round-up), daily and weekly

**Stored issues (owner, 2026-11-12: both, each on its own schedule)**: `mx_roundup_issues` (migration 0123). Each
closed day (local midnight to midnight) and each closed week (local Monday to Monday) gets one issue, built 6 hours
after its period closes (`ISSUE_SETTLE`: a digest of a day arrives the next morning; its items' times put it in its
day), at the offset in mx_settings `roundup_tz_offset_minutes` (default 240, the owner's UTC+4; `GET|POST
/api/markx/roundups/settings`). Built by the candidates job's step (`jobs._issues_step` → `units.issues_step`: the last
7 closed days and 2 closed weeks with no issue yet), inside that job's own spawned process, never in the API. A
period waits while a post dated from 2 days before it on was never split (a first backfill still under way, newest
first): its issue is written once, so never from a half-split copy. A past issue is never changed: `build_issue(..., rebuild=True)` (by hand) writes a new version row of the same period, and
readers read the newest version. `GET /api/markx/roundups/issues` gives the latest daily and weekly (with their items)
and the past ones; `GET /api/markx/roundups/issues/{id}` one issue. The /markx News tab shows a small "Own round-up"
section: daily / weekly, and the past issues to open.

**The digest** (`units.digest(cur, span, until)`: what an issue is built from; no route computes it, as nothing is built
in the API). The units whose time is in the span, grouped by what they carry (the Mark X story holding the attached post, else its Mark IX story,
else the post; an item attached to nothing by its first page that is no reference page), ranked by curators (separate
round-up sources carrying it: a site's own newsletter listing its own article curates nothing), then what INSIGHT
holds, the issues carrying it, the latest. `only_roundups`: nothing attached and no post outside round-ups links its
page in the span. A page a source's round-ups link in 4+ issues is its signature (a profile, a licence), no item.
`GET /api/markx/roundups/of?posts=` gives the also-in lines for any posts.

### 5. Never a voice

A unit is never a voice, a member, a mention, a News count or a corroboration: nothing reads `mx_units` / `mx_attach`
but units.py, and Pairing reads only `mx_roundups.issue_at` (its post date) and posts (its attach source). Tests
(`tests/test_markx_units.py`):

- a scan of the code: no module but units.py and pairing.py names the units tables (the migrations aside), and
  pairing's only one is `mx_roundups` (the issue time); event_types.py names only `mx_unit_types` (round 2: the
  items' types, read by units.py through the seam);
- on the seeded world of 0166 plus three round-ups whose items link its posts: two rounds of the decision run (tasks,
  memberships, connections, News rows with voices, reports, shares and mentions, back rows, later rows) and the
  anchors' voices are the same with every unit and attach row as with none;
- a story's anchor voices are its members' sources whichever round-up lists it.

The same file tests the splitters on fixture HTML, the tag, attach on fixtures (window, round-up, itself, unstored
pages), the issue time and every Pairing caller's identical result for ordinary posts (`PostDateIdentity`), the
digest (curators, own-source curation, only in round-ups, signatures), the stored issues (periods at the offset, built
once after settling, a rebuild a new version, the boundary a setting) and migration 0123. The frontend:
`components/markx/roundup.test.tsx`.

### 6. Round 2 (owner's review of 13 Nov: two dailies and a weekly read)

The weekly's top was good; the dailies were not: non-news items (an essayist's "N years ago" back-references, the
author's book ads and event dates, a newsletter's fun extras), fragments (a release note's second paragraph as its own
item; a newsletter's numbered story shown by its sub-sentence, its bold headline lost) and an arbitrary order (most
daily items have one curator). Fixed as classes, no site named in code:

- **Types and headlines by the worker** (kind `unit_types`, guide unit-types-v1, migration 0125): each item of a
  recent round-up (TYPE_DAYS = 16 back) is asked, UNITS_PER_QUESTION = 20 a question in the round-up's order (the item
  before the first shown for context), its type, a headline of at most 14 words and whether it only `continues` the
  item before it. The types are read-v3's for one item through the event-type seam (`schemas.UNIT_TYPES`,
  `event_types.UNIT_NEWS`, `event_types.of_units`), with the owner's `promo` (an ad; the author's own book, talk,
  event dates, sign-up; a bare link said nothing about) in place of `promotion_event`, and no `digest`. A new question
  kind rather than read-v3 extended: read-v3 reads one post whole (its reading, entities' main, origin); an item needs
  only a type and a headline, and twenty of them share one round-up's context. Keyed by the item's words (sha256 of its
  text: `mx_unit_type_asks`, `mx_unit_types`; the first answer stays), so a new split of the same words (any code
  change re-splits) is never asked again. Planned by the units step (`units.backfill` → `plan_types`, at most
  TYPE_PLAN_MAX = 60 questions a run), in the candidates job's process; the answer is stored by `tasks.record`
  (`units.after_types`, a few rows, as every kind's answer is). The worker asks one question a call
  (`unit_types=1` in its PER_CALL; the owner's worker needs `unit_types` in its --kinds).
- **An issue keeps news only**: an item typed outside UNIT_NEWS (model, product, research, business, policy/legal,
  incident, public statement, leak/rumour) or that `continues` the item before it is left out and counted
  (`left_out` on the issue: {type: n}); an untyped item is kept and counted (`untyped`). The headline is the Mark X
  story's, else the worker's, else the attached post's title, else the item's lead. A settled period waits up to
  TYPE_WAIT = 18 h (from its settling, or from when its round-ups' items were last asked) for its items' types.
- **Splitter, paragraph items** (`lines`): when leads (a paragraph whose first words are a link or bold) open half the
  paragraphs that link, an item starts at a lead (its bold line its headline, numbering dropped), at a heading over
  plain paragraphs (the heading its headline) or at a plain paragraph with a link of its own after an item that has
  one; its <br> lines (a story's sentence and "+" related links) and the following paragraphs with no link continue
  it. A short bold paragraph with no link is a label (a heading). Whether a later paragraph with a link of its own is
  more of the last item ("This release also adds …", "The 2.1 release notes list …") is meaning: the type question's
  `continues`. Fixtures of both shapes (a numbered newsletter, release notes) in the tests.
- **Ranking**: what INSIGHT holds as a story or 2+ curators carry first (by curators, issues, latest); then
  single-curator items attached to a stored post; then single-curator items attached to nothing, SOLO_PER_SOURCE = 5
  a round-up source (`capped` counts the rest: in a daily most items are single-curator and one 40-item round-up
  would fill the issue with its own list; on the server copy's 2 Nov daily 3 sources gave 85 of 100 rows). Inside the
  last two tiers the round-ups' own order (an item's place: editors lead with what matters).

## Measured (the local scratch copy: 49,384 posts, 5,344 read; private rows in the notes)

- **Round-ups**: 370 of 49,384 posts (115 by the reading of 126 it names; 255 by a digest's shape in a digest source:
  4 sources). By title, the shape-tagged ones are 254 of 255 periodic digests or newsletters (one essay of a monthly
  notes source). Without the digest-source rule the shape alone tagged about 50% essays outside the one big digest.
- **Units per round-up**: median 36 (p25 18, p75 147, max 325); 29,600 units in all. Adapters: list 256, lines 69,
  reading 24, sections 21.
- **Attach**: 1,275 rows (1,176 units, 239 round-ups, 789 posts, 248 Mark IX and 44 Mark X stories); 212 round-ups
  got an issue time, mean shift +6.8 h (−48 h to +42 h).
- **40 attach rows read blind** (random, final code): 39 right (item → post and its story); the wrong one an item whose
  subject was another matter while it linked a release post as context. Earlier rounds, before the fixes: 32/40 (a
  section's mega-item swallowed the rest), 34/40 (malformed nested lists), 38/40 and 38/40.
- **20 digest rows read** (a week on each of two dates): 17 right; wrong: an item grouped under a story its context
  link belongs to, a source's back-reference to its own year-old issue, an item grouped under a different thing it
  links.
- **Issues**: built on the copy in a spawned child as the jobs runner does, 7 days and 4 weeks a run (a catch-up):
  4.7 s and 7.6 s, the child's peak RSS 46 and 52 MB (38–39 MB of it the interpreter and imports before the build).
  A normal run builds 0–2 issues. Weeks of the copy: 19–42 round-ups, 506–808 units, 463–753 items, curators at most 2.
- **Cost**: a backfill step of 1,000 posts 0.5–2 s (the scratch copy split whole in 12 steps). Pairing's post date on
  its callers' queries: back's recent posts 30 ms before, 22 ms after; the Posts window 33 → 21 ms; newest-first 2,000
  ordered by the date 1.7 → 23 ms (the expression index no longer applies; once a candidates run).

### Round 2, measured (a clone of the server copy the owner's three issues were built on; private rows in the notes)

- **The same three issues rebuilt** (two dailies, 2 and 3 Nov local, and the week of 26 Oct), every post split with
  this code and every item typed by Haiku through the worker's own call (`claude -p`, one question a call):
  - daily 2 Nov: 107 items read; 45 news; left out 21 other, 6 promo, 9 opinion, 1 community post, 25 that
    continue the item before (20 of them an essay's citation paragraphs); 24 news items over the per-source cap;
    21 shown. Before: 100 shown, 33 of them an essayist's back-references and bare citation links, 26 a numbered
    newsletter's sub-sentences, related links and extras.
  - daily 3 Nov: 72 read; 24 news; left out 29 promo (the author's books, talks and event dates), 11 other, 4
    continue, 2 opinion, 2 community; 5 capped; 19 shown.
  - week of 26 Oct: 731 read; 94 shown, its top unchanged in kind (stories and two-curator items first).
- **Both dailies read end to end** (40 items shown): 39 are news items with a readable headline (97.5%); the one
  not: an interview link typed `public_statement`. Every headline says the happening (a numbered newsletter's item
  shows its bold line's story, not its sub-sentence). Over the cap and so not shown: 29 real news items (most of one
  40-item release digest and half a numbered newsletter's ten).
- **The type question, 40 items read blind** (random over all 1,788 answered items): 37 right (92.5%). Wrong: a
  job posting typed `business_event` (kept as news); an item reporting a new study typed `opinion_analysis`; a quote
  reporting incidents typed `opinion_analysis` with a headline that missed them. `continues` on the release digest:
  "This release also adds …", "The 2.1 release notes …", a compaction paragraph of the item before: all three
  `continues`; "Also out: <a tool> v0.3.1" a separate `product_release`.
- **Cost**: 132 questions for 16 days of round-ups (TYPE_DAYS), about 8 a day; 1,788 items, 13.5 items a question;
  4,231 tokens in and 2,466 out a question, 13.5 s; $0.0017 a question by Claude Code's count ($0.23 for the 16
  days, about $0.014 a day). A first run's backlog: 132 questions, TYPE_PLAN_MAX (60) a candidates run. Answers: 132
  of 132 valid within two tries under the final guide (the first wording's single-object answer was missed one time
  in seven without the question's `id`; the guide now asks for it).
- **Memory and time** (each in a spawned child as the jobs runner does): planning the questions of 16 days 3.1 s, peak
  RSS 45 MB (41 MB of it imports); a catch-up of 7 days and 2 weeks of issues 19.5 s on a loaded machine (load 13),
  peak 49 MB; three issues rebuilt 5.2 s, 47 MB. A normal run builds 0-2 issues.

## Not measured

- The server's data (never touched): the copy's newest posts are of 5 Nov; only one large digest source; curators of
  2+ are rare on the copy (one row in a week), so the curator ranking is untested at scale.
- Long newsletters the reading names but whose HTML gives no items (24 split by the reading's own items): read only
  inside the 40.
- A newsletter whose lead story's title is a plain paragraph (no heading, no bold) after an intro that links: the
  lead's paragraphs join the intro item (its link comes after them), so its own item is only "Here's how …". Seen once
  on the copy; the type question reads the joined item as a whole.
- The type question's accuracy on round-ups in Russian (2 of the 40 read, both right) and on sources not on the copy.
- "Only in round-ups" is exact by construction on the copy's posts; whether those items matter to the owner is his.
- A round-up tagged by its shape alone (255 of 370) is still a whole post to Pairing's same-story gates (they exclude
  only a reading's `roundup`), so it can stay a story's member and voice as before this slice; its issue time (made
  from its attached items) can move it across a window by hours. The seeded-world identity test covers round-ups the
  reading names only; the effect on the decision run of a shape-tagged round-up's moved date is not measured.

## Next

- News rows "also in round-ups" (news.py, after slice M).
- Units into Pairing's same-story sources (a unit's text embedded and paired like a post; a happening key for an item).
- The cap's size (SOLO_PER_SOURCE = 5) is a reading choice, not measured against the owner's taste: a daily shows
  about 20 items; the left-out news is counted on the issue (`capped`).
- A rebuild of a past issue from the page (today by hand: `units.build_issue(cur, span, start, rebuild=True)`).
