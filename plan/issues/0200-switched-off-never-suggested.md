# 0200: A source switched off is never suggested (Stealth v10.17.1)

Status: **built** (branch `v10171-disabled` from `main` at v10.17). Not merged, not pushed, not deployed. Migration
**0135**.

## The problem

On the server (v10.17) the owner switched off a source (an SEO content farm). A topic track's Discover list still
showed that source's posts at its top (a listicle, confidence 0.95). The class: every list that
proposes something read posts and sources with no regard to the owner's switch. A track's Discover and its joined
items, its source suggestions, the scout's posts, Discover's sites (by links and by the stories that start there), its
Pages, archive rows and citations, 0170's "main source missing" (which even surfaced a switched-off source as a
`disabled` row, asking to switch it on) and the voices' suggestions all counted a switched-off source like any other.

## The rule

**A source the owner switched off (`sources.enabled` false) never feeds a suggestion.** Its posts are no evidence for
any list that proposes something to follow, read, join or archive, and its address is never proposed. It stays
followed: a site or account it holds is not suggested either (switching a source off is not "unfollow and show me it
again").

One predicate, in the module that owns source facts (`backend/insight_core/db/repo_stories.py`):
`suggestable_sql(column)` (SQL), `switched_off(cur)` and `SourceFacts.suggestable(source_id)` (Python), all reading one
definition (`_SUGGESTABLE`). Every list asks it; none restates it. `markx/source_judge.py`, which already read
`s.enabled` in six places, now asks the same rule.

**News, stories and Classics: unchanged.** A switched-off source's stored posts keep their places and still count as
voices there (today's rule): membership is what happened and who reported it, not a proposal; changing it would move
News rows and story trees every time the owner tidies the source list. Only suggestions change. A switched-off
source's post the owner marked ✓ in a track stays in the track (the owner's own label is no suggestion); collecting
originals and references (0123, 0138) still reads its posts.

## Built

| list | where | what changed |
|---|---|---|
| Track: Discover and joined | `markx/tracks.py` `placed` | Haiku's in from a passive source switched off is placed `off`: neither in Discover nor joined. Calibration unchanged. `counts.off` on the page; `track_why` says `off` |
| Track: kept placements | migration 0135 | a trigger on `sources.enabled` logs every topic track (placed again live, then kept); the migration logs them all once, so placements kept before it are redone |
| Track: source suggestions | `tracks.suggestions`, `track_kept.suggestible` | never a source switched off |
| Track: the planner | `markx/finders.py` `score` | a passive post of a source switched off is never asked (recent and history passes): no Haiku spend on what can only become a suggestion |
| Scout (finder 1, item names, terms) | `markx/scout.py` `in_posts` | Haiku's in from a source switched off is not read; the owner's ✓ is |
| Discover: sites by links | `db/repo_discover.py` `_COUNTS` | its links and reposts are no voice; the kept counts' stamp and the incremental path follow the switch |
| Discover: sites by stories, Pages, archive rows | `story_origins`, `_discover_all` | a story's voices are its sources' not switched off; a story holding a post of a switched-off source that the others leave under 2 voices starts nothing here (a story with none keeps the story job's count: 96 stories on the copy have a stored count unlike their distinct voices, and a first version that recounted every story dropped 58 of them for nothing); no archive row for a source switched off |
| Discover: activity (opened) | `_ACTIVITY` | its posts not counted |
| Discover: citations of long-reads (F3) | `originals_service.longreads(suggesting=True)` | its long-reads cite nothing for Discover |
| Discover: entity Pages (D1) | `plan_entities(listing=True)` | its mentions are no voice of a Page; collection unchanged |
| Discover: supplied first (D3) | `supplied_first` | the same rule (was `WHERE enabled`) |
| Main source missing (0170) | `services/discover_main_source.py` | its posts are no member of an event; a channel only it covers is no row; the `disabled` kind is no longer made (the frontend's branch for it stays, unused) |
| Voices | `services/voices_service.py` `shape`, `_not_followed` | a switched-off source is in no suggested voice, possible or related pair, and has no "not followed" channels; read as things stand (kept verdicts stay, so switching it on brings them back) |
| Research channels, scout candidates | unchanged | they come from the web; a switched-off source's address is still followed, so never a candidate |

Not changed (second-hand, kept between runs): Discover's suppliers of originals (D2) and the rabbit hole's worlds (E4)
read collected originals and the entity graph, which are membership, not evidence picked per source.

## Tests

`tests/test_switched_off_0200.py` (the rule; Discover by links, by stories, Pages, archive rows; voices),
`test_markx_tracks.SwitchedOff` (Discover, source suggestions, counts, kept placements through the trigger, joined,
the owner's ✓, the planner, the scout), `test_discover_main_source` (a switched-off covering source and a switched-off
member: no row; the old `disabled` tests replaced), `test_entity_originals` (citations, entity Pages). Each one: the
switched-off source's posts are absent, an enabled source's are there, switching it on brings it back. Test fixtures
for "your sources" (`_stories.insert_source`, `_Api`'s two sources, and the Discover fixtures of test_stories, test_news and test_markx_event_types) are now on: before, every scratch source was off
by default, which this rule would have read as switched off.

## Measured (a clone of `prep_mxreal`, 49.4k posts to 5 Nov, 7 sources switched off with 5,543 posts; tracks on a clone of `prep_scale`)

Every list made by `main`'s code and by this branch on the same copy, at the same `now`:

| list | main | this branch | gone | new |
|---|---|---|---|---|
| Discover suggestions | 1,234 | 1,176 | 61 (48 linked by a switched-off source's posts; 13 X accounts with no such link, reached through a switched-off X feed's reposts or stories: not checked one by one) | 3 (two hosts a gone card held as its places, now their own; one account that was "also <a switched-off source>'s", linked by 3+ enabled voices) |
| Discover "also" (other channels) | 22 | 20 | 2 (both a switched-off source's) | 0 |
| Discover references | 24 | 23 | 1 | 0 |
| Discover Pages | 50 | 47 | 3 | 0 |
| Discover archive rows | 7 | 7 | 0 | 0 |
| Story roots Discover reads (2+ voices) | 945 | 901 | 44 (each with a switched-off source's post) | 0 |
| Voices: suggested voices | 16 | 12 | 4 (each with a switched-off source) | 0 |
| Voices: possible / related / not followed | 10 / 17 / 94 | unchanged | 0 | 0 |
| Main source missing, entity Pages, citations | 0 | 0 | (this copy has no read-v3 and no opened long-reads) | |
| Track Discover (4 tracks, judged in) | 2,659 / 2,718 / 2,832 / 2,827 | 2,312 / 2,477 / 2,496 / 2,494 | 347 / 241 / 336 / 333 now `off` | 0 |
| Track Discover, the 100 shown | 100 each | 100 each | 12 / 6 / 13 / 13 of the shown replaced (none in the top 10 on this copy) | |
| Track source suggestions | 9 / 9 / 5 / 12 | 8 / 8 / 4 / 11 | 1 each (a switched-off source) | 0 |
