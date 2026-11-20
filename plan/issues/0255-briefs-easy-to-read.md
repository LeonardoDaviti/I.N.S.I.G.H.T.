# 0255 — Track briefs easy to read (v10.29)

Status: **built** (owner 2026-11-21: "identify issues ... focus on ease of information consumption"; "build them as
fast as possible"). Found reading the four server tracks' first briefs (208 rows, the counts private).

Built in the brief's view (markx/track_brief.py; nothing re-read, nothing deleted, every value stays in its row and
in the tables):
1. **New means new** (`fresh_from`, the quick look and the rail's count): a thing found since the look whose first
   post is dated since the look or in the week in progress. A backlog read after the look goes to its week's issue
   and the tables. The first open showed months-old rows as new.
2. **Practices inside their things** (`_fold_practices`): a practice every post of which also gave a thing of the
   track's kinds is shown inside the newest such thing ("– what → result"); a practice with only its `what` (no
   result, no evidence) is not shown in the brief. A point citing a folded practice cites its thing. On the server's
   rows: Cool Projects 54 -> 17 practices listed (34 inside), Local Setups 54 -> 34 (18 inside), Agentic Workflows
   38 -> 5 (28 inside).
3. **Quiet columns** (`_quiet`): with 5+ rows, a column filled in under 20% of them, or a choice whose one value fills
   over 60%, is left out of the section (an empty price column, a type that is "open source tool" in most rows).
4. **Values that say nothing**: a choice of "other" is shown blank; a practice's evidence that only repeats its
   result's figures is not shown; a bare number takes its field's unit; a raw GitHub file link opens as its repo page
   (`track_things.reader_link`).
5. **Links in INSIGHT**: a row's ↗ opens the post in INSIGHT (a post's address can be a feed bridge's, e.g. the
   server's Nitter, that the reader's device cannot open); the quick look shows 5 rows a kind, "see all" the rest.
6. **digest-v3**: the points state facts (no reporting words, no hedges, one subject a point); every week asked again.

Not done here (measured later / next): the schema guide (a separate model field, a "release to run" kind, units
required) changes every track's schema and re-reads its posts: after the bars of 0245 are measured. The 3D track's
0 rows from 10 posts: its things answers to be read on the server.
