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
7 closed days and 4 closed weeks with no issue yet), inside that job's own spawned process, never in the API. A
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

- a scan of the code: no module but units.py and pairing.py names the units tables (the migration aside), and
  pairing's only one is `mx_roundups` (the issue time);
- on the seeded world of 0166 plus three round-ups whose items link its posts: two rounds of the decision run (tasks,
  memberships, connections, News rows with voices, reports, shares and mentions, back rows, later rows) and the
  anchors' voices are the same with every unit and attach row as with none;
- a story's anchor voices are its members' sources whichever round-up lists it.

The same file tests the splitters on fixture HTML, the tag, attach on fixtures (window, round-up, itself, unstored
pages), the issue time and every Pairing caller's identical result for ordinary posts (`PostDateIdentity`), the
digest (curators, own-source curation, only in round-ups, signatures), the stored issues (periods at the offset, built
once after settling, a rebuild a new version, the boundary a setting) and migration 0123. The frontend:
`components/markx/roundup.test.tsx`.

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

## Not measured

- The server's data (never touched): the copy's newest posts are of 5 Nov; only one large digest source; curators of
  2+ are rare on the copy (one row in a week), so the curator ranking is untested at scale.
- Long newsletters the reading names but whose HTML gives no items (24 split by the reading's own items): read only
  inside the 40.
- "Only in round-ups" is exact by construction on the copy's posts; whether those items matter to the owner is his.
- A round-up tagged by its shape alone (255 of 370) is still a whole post to Pairing's same-story gates (they exclude
  only a reading's `roundup`), so it can stay a story's member and voice as before this slice; its issue time (made
  from its attached items) can move it across a window by hours. The seeded-world identity test covers round-ups the
  reading names only; the effect on the decision run of a shape-tagged round-up's moved date is not measured.

## Next

- News rows "also in round-ups" (news.py, after slice M).
- Units into Pairing's same-story sources (a unit's text embedded and paired like a post; a happening key for an item).
- A rebuild of a past issue from the page (today by hand: `units.build_issue(cur, span, start, rebuild=True)`).
