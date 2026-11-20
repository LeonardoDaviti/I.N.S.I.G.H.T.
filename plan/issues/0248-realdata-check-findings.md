# 0248 — what the v10.26 real-data check found, and the fixes

Status: built on a branch from v1026 (with e7ba1dff, every entity relation on). Not merged, not pushed.

The check (v10.25 + v10.26 against origin/main = v10.24, in place on one copy of the server's data) failed on the
decision run's resources, four Discover invariants and one case, a News row's lead, and one story invariant. Every
number below is on that copy (162k posts), clock 2026-11-19T16:58, each job in a process of its own as
`checks/resources.py` runs it; the private report names the rows.

## 1. The decision run (`decide`, incremental): not a code regression at equal state

The check: 904.5 MB, 105.8 s, CPU 78.9 s, against the base's 695.6 MB, 91.7 s, CPU 47.8 s. Each side's incremental
run followed its own full run on its own restore, so the two compare different states (the entities stage's full
pass, its link backlog, the tasks each code's full run left).

Measured here on one state for both codes, each stage's own peak (VmHWM reset at each stage) and CPU, in the check's
order (the other code's state, then a full run, then the incremental run):

| incremental run | peak MB | wall s | CPU s | its peak stage |
|---|---|---|---|---|
| v10.24 (base) | 729.6 | 111.4 | 61.1 | entities 729.6 MB, 44.2 s CPU |
| v10.26 + relations on | 750.6 | 106.1 | 65.3 | entities 750.6 MB, 48.1 s CPU |
| v10.26, a second state | 741.8 | 101.9 | 59.9 | entities 741.8 MB, 39.0 s CPU |

Within 3% (peak) and 7% (CPU) of the base. The stages moved, not the total: the graph stage's relation scope (0244)
fell from ~19-28 s to ~4 s, and the relations turned on (e7ba1dff) add a backfill of 9,000 posts a run (~17 s wall,
~3 s CPU) until it has read every post (~18 runs); the news stage's one-release grouping (0236) adds ~1 s.
The full run fell from 1,280 MB to 783 MB.

Not fixed: the budget (600 MB, 90 s). The base is over it too: the entities stage alone takes ~330 MB over what the
run holds before it (its whole entity book, 0204), on both codes. Cutting it is its own work (the book read in
parts), not a regression of these versions.

## 2. Discover

| | base | v10.26 | fixed |
|---|---|---|---|
| `discover.followed_host` | 1 | 4 | 2 |
| `discover.name_address` | 1,928 | 2,172 | 2,169 |
| `discover.title_slug` | 64 | 75 | 75 |
| case `discover-unfollowable-not-last` (rank ≤ 60) | 23 | gone | 21 |
| suggestions gone since the base | | 36 | 11 |
| the build (seconds, CPU, peak) | 10.2 s, 5.9 s, 471 MB | 20.0 s, 6.7 s, 479 MB | 11.1-14.0 s, 5.9-6.1 s, 510 MB |

- **A company's two followed sections made it a site of publications.** 0239 reads a site of publications
  (each host a site of its own, for what you follow) from `SourceFacts.shared_sites`: a site your website sources
  publish on at 2+ hosts. A company whose newsroom and engineering blog you follow is such a site, so its other hosts
  (a mailing-list archive) and the company itself (its main host) came back as suggestions. Fix
  (`StoriesService._publication_sites`): a shared site is one of publications only when the data says so too
  (`discover_rules.federation`, 10+ hosts at under 4 posts each): measured, a newsletter host 1,668 hosts at 2.6, a
  blog host 377 at 1.6; the companies 17-64 hosts at 19-242. Left: a public-suffix government host (as the base),
  and a blog platform's own host while you follow one blog there: by 0239's rule a publication followed hides none
  of the platform's others, and the platform's own blog is one of them (the invariant reads any host under a followed
  one as followed).
- **The card's announcing section led over the site itself.** 0239 leads a card by its newsroom/blog/press host over
  a best that is an investor-relations host. It also led over the site's own host: a news publisher's card was led by
  its old `blogs.` host (the case's suggestion gone, the judge reading a dead blog). Fix
  (`discover_rules.one_card_per_domain`): the announcing section leads over another section, never over the site's
  own host. 25 of the 36 gone suggestions are back.
- **`name_address`, `title_slug`: the base's classes on the new suggestions.** The names that are addresses are the
  same 42 sources' names in both (decision 1 of 0080, not built), repeated on the new rows (224 of the 260 new pairs
  are repositories' rows). The 11 new slug titles are all on publication hosts 0239 now suggests, titles that spell
  their slug (0080: "link words or stored titles that spell the slug").
- **The build: the repositories' query.** `DiscoverRepository.repos` (0239) took each repository's most linked pages
  in a subquery per repository over every kept link: 4.9 s. One grouped pass (a window per repository): 0.49 s, the
  same 1,640 rows. The peak (510 MB at this state, the base 471 MB at its own) is over the 300 MB budget on both: its
  largest part is the entity names read for the originals rows (`rabbit_hole.discover_rows`, ~9 s on both).

## 3. News: a row's lead moved to a later repost

The row of a filing (a collected page, its feed missed it) was led by the filing on the base and by a repost of a
report on v10.26. No rule of News moved it: 0156 B redated the filing. It is dated by its first stored linker; v10.25
counts a linker from `GREATEST(published, metadata.modified)` (an essay edited years later to add the link). The
filing's first linker, a report at 11:40, was updated at 15:42 the same day, so the filing took a later report's
14:01 and a repost at 12:34 became the row's first post.

Measured on the copy: of 47 collected pages 0156 B redated, 24 moved by a linker changed within a day of its
publication (minutes to hours: the same piece corrected); the other 23 by changes days to years later (the class
0228 meant). Fix (`saved_service.LINKED_SINCE`, the one expression, and 0156 B with it, not yet released): a linker
counts from its change only when the change is more than a day after its publication (0156 A's own tolerance).
After the repair and the story job on the copy: the row's lead is the filing again, and no News row's lead differs
from the base's (the "lead changed" row of the report is gone too).

## 4. `story.deploy_identity` 16 → 18: the base's class

The two rows more are one more `stories` row each side: a story whose voices are 3 after a deploy's first start and 4
after the full rebuild, its fourth voice a roundup that mentions it (`story_mentions`). The base's 16 hold the same
kind (stories at 2 → 3, their extra voice a mention); `deploy_lost` is the same 2 posts on both. Which stories the
deploy's queue reaches differs with the queue (4,806 posts on the base, 4,195 on v10.26). Not fixed here: the
incremental job's voice count of a story whose mentions changed is its own issue.

## The cases marked pass that fail on both sides (stale: the case set is the Nov 5 lab copy's)

- `kimi-k31-pro`, `reddit-release-is-not-roundup`: name lab story ids this copy does not have.
- `search-kimi-31`, `search-news-filter-titles`: name posts or titles the server's copy lacks in its search window.
- `discover-openai-archive`, `discover-x-accounts`, `discover-x-titles`, `discover-one-title-per-page`: counts and
  keys of the lab's Discover (its X accounts, archive origins).
- `roundup-opens-about-the-story`, `origin-title-link-post`, `news-name-in-slug`, `news-voices-named`: rows of the lab's
  window, not in this copy's News window.
- `substack-writers-voices`, `lfm3-styled-name`: counts and an origin of the lab's data (the server's posts differ).
- `saved-is-not-a-voice`, `covered-by-one-voice`, `post-page-also-shared`, `google-devblog-undated-top`: saved or
  collected posts the server never stored.
- `hn-row-counts`: a post's counts the server's copy does not keep.
- `date-alone-news-window`: a minute of the lab's feed (18:01); the server's copy stores 18:00.

## Tests

`test_discover_cards_0239` (the site keeps its lead; a company with two followed sections followed; a platform's
writers need the federation test), `test_archive_site_and_dates` (a linker corrected the same day; 0156 B keeps its
date), with `test_discover_growth_0235`, `test_discover_counts`, `test_discover_from_server`, `test_names_and_joins`,
`test_saved`: OK.
