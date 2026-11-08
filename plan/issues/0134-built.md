# 0134 — Built (Stealth v10.8): Series

Built 2026-11-08 on its own branch, test-first, the spec's parts 1–4 (the Mark X panel and the source page aside, see
"Not done"). No model. Migration **0083**.

## What was built
1. **The rule** (`utils/series.py`): the lab's frozen `series_v1.py` ported, with the spec's five fixes.
   - E1 numbered titles (part-style, issue-style, runs of 3+ "stem N:"), E2 navigation links, E3 a shared start
     (stored or not). Groups are connected components within one source. A weak "previous post" link alone is no
     group. Kind: column when its markers are mostly issue-style and it runs long or its stem recurs; else series
     (the rule-only default the lab measured).
   - The fixes:
     1. no E4;
     2. on X, a marker counts only at the start of the title;
     3. an unmarked post titled exactly with a series' stem, before its part 2 and within 60 days of it, joins as part 1;
     4. 60 days between parts;
     5. no cap on part numbers, and a letter may follow ("32a"; 34a and 34b are two parts).
   - **One departure from the lab:** its BGE-M3 cosine check for a looser stem is not ported. Mark IX reads no Mark X
     vectors, so a looser stem needs the lab's other sign, the posts within 3 days, as the lab did for a post with no
     vector.
2. **Storage** (migration 0083):
   - `series` (id, source_id, kind, stem, name (the stem as written), total, first_at, last_at, evidence, computed_at,
     valid_to) and `series_posts` (series_id, post_id, number as written, position).
   - `post_refs.navigation` and `post_refs.navigation_at`.
   - **The pass** (`db/repo_series.py`, `SeriesRepository.run`) runs in the story job right after the refs are read
     (`StoriesService.fill_series`). It has its own transaction and advisory lock, and a failure is logged without
     stopping the story job.
     - It reads again the sources with a post stored or changed, or whose refs were read again, since the last pass
       (an hour of overlap). The first time, and after a `series.VERSION` bump, it reads every source: the backfill.
     - Each source's groups are made again from all its posts. A group that is unchanged is left; a changed one is a
       new row, and the old one is closed (`valid_to`), never deleted.
     - The links' words are read only from the posts whose HTML may hold a navigation link (`NAV_PREFILTER`, a
       superset of the rule's words).
3. **Navigation marked:**
   - `post_refs.navigation` is set on a source's open refs: a same-source link whose two ends are in one group, or
     whose link words are navigation.
   - **Connected:** `GET /api/posts/item/{id}/connected` drops those rows from Earlier and Later. It adds `navigation`
     (those rows, each with its `group`) and `series` (the line, below).
   - **0131:** an author-link edge over a navigation ref is `relation='next_in_series'`, `rule='series'`, p 0.9. The
     judge never plans or refines it (`graph.JUDGED_LINK_RULES`). A changed flag (`navigation_at`) re-reads the edge.
     `series` is in `LINK_RULES`, so `markx.author_link_resolves` checks these edges too.
4. **Where it shows:** the post page, at the top of the Connected block (its lazy chunk).
   - A series: "Part 3 of 4 in ‹name›", ‹ Previous part / Next part ›, and the stored parts in order (this post
     unlinked).
   - A column: "Issue #136 of ‹name›" and the previous and next issues.
   - Navigation links whose post is not among the parts are listed under the line. On a phone the parts fold; prev
     and next stay.
   - "of N" is the largest of: a part's declared total, the largest number, and the count of stored parts.
5. **The invariant** `series.source_posts`: every `series_posts` post belongs to the series' source.

## Tests
- `test_series` (29):
  - each E1 pattern in English and Russian, and what is not a marker;
  - E2, weak links, roundups; E3;
  - the owner's case shape (parts 2/3/4 with an unstored start);
  - each of the five fixes;
  - kinds;
  - the navigation rule, and the link words by address;
  - on the database: storage, navigation in `post_refs`, the line, Connected's split, an incremental pass (unchanged
    left; changed closed, never deleted), the dirty sources, the pass's clock, the invariant.
- `test_markx_graph` (+2): a navigation ref is next_in_series and never judged; a flag turning off reopens refers_back
  and closes the old edge.
- Also run: `test_post_refs`, `test_migrate_runner` (`series_posts` among the derived tables), `test_realdata_checks`,
  `test_stories`, `test_incremental_stories`, `test_deploy_finishes`, `test_post_page`, `test_news`,
  `test_story_trees`, `test_markx_storage`, `test_markx_api`: 357 tests, OK.
- Frontend:
  - `components/post/Connected.series.test.tsx` (7): the line, prev / next, the parts, a column, navigation rows, no
    series, an older server, the phone;
  - the existing Connected tests pass;
  - `npm run build`: feed route −0.00%, post route +0.00%.

## Real checks (scratch copy of `insight_server_1105_mxreal_sep`, migrated to head, dropped after)
The copy was at 0068, so 0125's refs were read first: 49,384 posts in 116 s.

| | Result |
|---|---|
| The pass, every source (the backfill) | **16.1 s** for 251 sources: 90 groups (79 series, 11 columns), 291 posts, 36 sources |
| Against the lab's 138 groups / 449 posts | Every difference is on X. The lab's 51 X groups were E4 self-reply threads, which fix 1 removes. Off X: 89 groups against the lab's 86 (+3.5%). Every lab post off X was found again, plus 24 more (part 1s, past 30, 45–60 days) |
| The owner's case | parts 2 / 3 / 4 in one series, by E1 and E3 |
| Same-source Earlier rows marked navigation | 213 of 8,954 (2.4%); 235 refs marked in all |
| Same-source edges (0131 backfill, 10.8 s) | 45 of 4,637 are `next_in_series`; the other 4,592 stay `author_link_own` |
| The invariant | 0 bad |

A second pass right after re-read every source (their refs were read within the hour) in 14.0 s and changed nothing.

## For the owner
- **Not done:**
  - the fresh held-out re-measure (80 same-source Earlier rows and 80 same-source edges, lower bound ≥ 90%);
  - `scripts/realdata-check.sh`;
  - the owner's review of 20 series and 10 columns.
- **Not in this slice's files:**
  - the Mark X post panel's line (`markx/api.py`, `MarkXPanel`);
  - the source page's list of its series (0132).

  Both can read `SeriesRepository.line` and the `series` table.
- **At deploy:** the first story job runs the backfill pass, about 16 s on the server copy's size.
- **What could be wrong:**
  - A navigation flag is set only by the pass. A post whose refs are read again keeps its flag until the next pass,
    which reads that source again in the same story job.
  - The pass resolves a link within the source's own posts. An address stored under two sources resolves as the
    source's own.
