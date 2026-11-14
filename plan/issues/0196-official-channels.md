# 0196 — Official channels: Discover follows the original sources by itself (Stealth v10.18) — built, Shadow by default

Status: **built** (2026-11-14) on `v1018-official-build` from `v1018`; Shadow by default (the bar for the automatic add
is missed by 0.001 on its lower bound, in-sample: below). **Migration 0138.** Names below are invented; the real rows
are in the private notes (`plan/research/official-0196/notes.md` section G and `build/`, gitignored). The spec as
written on 2026-11-13 follows the "Built" section unchanged.

## Built (v10.18)

| Piece | Where | What |
|---|---|---|
| Official channels | `markx/official.py` (new) | the module: events -> actor -> candidates -> proof -> wanted -> would_add / added / refused / covered; the channel book (`book`), the review view (`view`), `undo`, the `cited` planner's rule (`pages_wanted`), the Discover check (`check_suggestions`) |
| Events, actor, own pages | `services/discover_main_source.py` (deepened) | `pick(min_voices=1)`; `events(bare=True)`: also actor-less events, each with its products and their code addresses (0138); `section_of`: a forum's `/c/<category>/`, never the container; `channel_of`: help, docs, CDN, file and app hosts and forum threads are no channel |
| Wanted + filter | `markx/source_judge.py`, guide `source-judge-v2` | the same test read (the feed finder, then page watching, an account through its kind) and one question; v2 adds `filter` {kind, hide [{field tag/title, regex, why}], keep}; a releases feed is read up to 30 items, a release's tag is shown after its title; callable from the jobs process at its own priority |
| Who and where | `websearch` kind, guide `websearch-official-v1` (`schemas.GUIDE_VARIANTS`) | one question an actor-thing pair, kept in `mx_official_lookups`; the worker asks it with the kind's own tools (WebSearch); its checks are the guide's (`validate.GUIDE_CHECKS`, the worker reads them too) |
| The maker | `markx/entity_facts.set_maker` | a facts row `by='web'` only where no maker is known; never `mx_entities.maker`, never another table |
| Handles | `markx/handles.entity_handles` | the actor's confirmed handles and its own sources' accounts -> its X account |
| Item filter | `utils/item_filter.py` (new), `source_filters`, `posts.filtered_by` | checks (compiles, a shape, never a plain release, hides one item read and none it keeps), applied at store time in `repo_posts.save_batch` (one query when no source has a filter), re-marked on change; hidden from the feeds and unread counts (`repo_reader.NOT_STORY_ONLY`) and from Mark X's read/entities/headline and embed planners; never deleted |
| Pages 2+ voices link | `services/originals_service.plan_cited` | one more planner inside the originals step, under Collect originals and the same credit, recorded `cited` |
| Discover by fit | `stories_service._by_fit`, `discover_rules.order` (`FIT_ORDER`) | within a section: judged follow-and-fits first, then maybe and the unjudged, then skip, then not fitting the reader; then link volume. The job asks the worker about up to 10 suggestions a day, those the sources you open most link first |
| The job | `markx/jobs.py` (`official`, every 30 min) | in its own process, never the API; budgets a pass: 150 events read, 20 handled, 10 test reads, 4 web searches |
| Review view | `routers/official.py`, `components/sources/OfficialChannels.tsx` | GET `/api/official`, POST `/api/official/{id}/undo`, GET/PUT `/api/sources/{id}/item-filter`; Discover's "Official channels": added automatically (Undo), would add, being checked, already followed, refused, undone; why, found from, owned, proof, the worker's judgement, the filter and its hidden items |

**Switches.** `INSIGHT_OFFICIAL` = `off` | `shadow` (default) | `on`; `INSIGHT_OFFICIAL_ADDS_PER_DAY` (default 5: the
first weeks' cap; above it a proven, wanted channel waits as `would_add`). On, the add is `scout.default_add_source`
(POST /api/sources' own path, at the address the finder or page watching resolved), settings `added_by: official`,
the item filter, then the archive back to the reading window. Undo switches the source off (posts kept) and the
module never adds that channel again.

**Rules learned while building** (the class, measured on the labelled rows): a code address of a thing (0138) is no
proof of who owns the repository (posts link plugins and forks of a thing: 6 of the first 99 candidates); a section
must announce (its path, or its read holds the event's page) — pages your sources link (a benchmark's data pages) do
not make it one; ownership also takes Discover's name rule (`discover_rules.own_names`/`same_owner`: a word of the
handle is one of the actor's names, starts or ends with it, a parenthesised other name counts).

### Measured at build (2026-11-14)

The census copy (posts to 5 Nov, Mark X stories and entities, read-v2 only), the census' 171 announced-type stories
as the events (the copy has no read-v3), the pass as the job runs it, the worker's questions answered by Haiku exactly
as `scripts/markx-worker` asks them.

| | |
|---|---|
| events read | 150 (the pass's cap); held 1, covered by a followed source 21 channels, not official 2, official source not found 17 |
| web-search lookups | 88 asked, $0.027 mean (min $0.0007, max $0.060), median 13 s |
| owned candidates (two blind labellers; positive = both say "official channel of this actor") | round 1: 80/99; **round 2, after the two rule fixes: 90/97 (92.8%, Wilson 85.9%)** |
| ... passed the proof (a dated stream, announcements) | round 1: 57/65 (87.7%, Wilson 77.6%); **round 2: 66/68 (97.1%, Wilson 89.9%)** |
| ... would be added (proof + gate + the worker's follow and fits) | round 2: 7/7 (Wilson 64.6%); covered 21/21 |
| item filter on 18 real release feeds (rule from the newest 10, applied by code to items 11-80, blind labels) | **real releases hidden 0/890 (Wilson of kept 99.6%)**; builds hidden 120/125 (96.0%, Wilson 91.0%); pre-releases hidden 92/118; every hidden item a build or a pre-release: 212/212 (Wilson 98.2%) |
| item filter cost | $0.0008 a channel, once |
| peak RSS of a pass's plan step | 58.7 MB, 0.9 s (150 events; the lazy book) |

Round 2 is in-sample (the fixes were made on round 1's errors, the same events), and its lower bound is 0.001 under
the bar (>= 97%, Wilson >= 90%): **the automatic add stays Shadow**. The two rows that are not both-yes are a maker's
company organisation for a person's product, both "unsure" for both labellers, both refused by the gate. The bar's
next measurement: Shadow on the server for two weeks, 40-100 of its `would_add` rows read blind (new events: held out).

### Cost a day (the server, ~3x the local copy)

| | a day |
|---|---|
| web-search lookups (~88 in 30 days locally, one an actor-thing pair) | ~9 x $0.027 = **$0.24** |
| `source_judge` + filter (proven candidates ~3/day + 10 Discover suggestions) | ~13 x $0.0011 = $0.015 |
| `cited` pages read by the worker's `read` (~40 fetches) | ~$0.08 |
| total | **~$0.34 a day** (under 1% of the worker's ~$43) |

### On / off after this build
- `INSIGHT_OFFICIAL=shadow`: every step runs and is shown in Discover; nothing is added.
- The item filter: on for any source that has a rule (none until a channel is added or the owner sets one).
- `cited`: on under Collect originals (on by default), under its credit.
- Discover's fit order: on (only changes the order where the worker judged a suggestion).

### Not done
- X accounts' proof by their first read: locally no X bridge, so X candidates were proven only where a followed source
  already covers them; the server's bridge gives the first read.
- GitHub's prerelease flag (the releases API): not read; rules are by tag and title only (measured above without it).
- The fit order's case (a practitioner far down Discover's link-volume order) is not measured on data: the local
  copies predate those suggestions.
- `cited`'s exclusions as code were not re-measured against the 30 pages read by hand (82% then).
- The bar for `on` (above).
- Mark IX's story job does not skip hidden builds (they get no Mark X reading, so no Mark X story).

## The spec (2026-11-13)

Status: **spec** (2026-11-13). Branch `v1018-official` from `v1016` (ed27739). Nothing here is code yet. Names below
are invented; the real rows are in the private notes (`plan/research/official-0196/notes.md`, gitignored).
**Migration 0134+** (number assigned at build).

## The owner's decision (2026-11-13, changing the 12 Nov "no blind auto-add")

"Discover should run automatically on the internet, find official postings and release feeds, and add them
automatically, to always stay in the cycle of the original postings and have true information." Non-official sources
are still never added by themselves.

The trigger: a forum post "<Engine> v1.0 is here" by an employee of a model hub, no links ("links in comments").
INSIGHT follows the engine's lead developer on X and the hub's blog, not the engine's release feed. The feed finder
finds `github.com/<org>/<engine>/releases.atom` at once (measured on the server: `found`; your sources link the
code host 2,356 times), but nothing runs it. And that feed also publishes the automatic builds (`b12361`, `b12360`, ...):
16.3 items a day, 99% builds (measured below). Raw following would flood.

Two later inputs from the owner, folded in here:
- **Don't wait for 0184.** When INSIGHT doesn't know who makes a thing, the worker's web search (0171's `websearch`
  kind) answers "who makes it and where do they announce"; the finder then proves the channel. The maker it finds is
  written once, through identity's one owner (0184's identity facts; until they land, the existing maker field by the
  existing path), never a parallel store.
- **Release vs build.** INSIGHT has no item filter today. A per-source item filter: when a channel is added the worker
  reads its recent items and proposes a rule; code applies it to every new item; builds are kept but hidden.
- **Pages 2+ sources link** are saved automatically (not every linked page), by the same proof, noise and
  keep-everything rules, deepening the originals step that exists (`collect_originals`), not beside it.

## What exists today (the map)

| Piece | What it does now | Its role here |
|---|---|---|
| `services/discover_main_source.py` (0170) | per Mark X story of 2+ voices and an announced type: the actor (`_actor`, `named_actor`), its own pages in the members' links (`owned_by`), the channel (`channel_of`: X account, Telegram channel, a site's section), the verdict (`missing`, `wrong_section`, `disabled`, covered). Rows in Discover; the owner taps Follow | **its rules move into the module** (actor, own page, channel, coverage); Discover's rows become the module's view |
| `ingestion/where_linked.follow`, `page_watch.preview` (0026, 0028, 0172) | the finder on an address (a feed, found, direct, none; `holds` = how many linked articles a feed keeps); page watching's preview | the proof's first half (a dated stream) — every add through them (memory: source-adding rule) |
| `markx/source_judge.py` (0173) | on the owner's tap: reads a candidate's 10 newest items, measures by code (rate, reads, health, rewriter marks), one Haiku call: follow / maybe / skip, `fits` the reader | the "wanted" gate and, extended, the item filter (one call a channel) |
| `markx/research.py` + `websearch` kind (0171) | a maker's other accounts by Claude's web search, for research runs | the "who and where" lookup when the post carries no own link (a new guide on the same kind) |
| `mx_entity_addresses` (0138) | a thing's own addresses: code (423 on the local copy), release (359), paper, work | a product's repository → its releases feed, without a search |
| `markx/handles.py` (0168) | handles cited, learned handle pairs, repost authors | an actor's X/Telegram handles as candidates |
| `mx_entities.maker`, 0184 identity facts (planned) | a thing's maker: first-run majority today; `entity_facts.read/place` planned | the actor of a product event; the web search's maker written back through it |
| `services/originals_service.py` (0114, 0123, 0138, F1–F3, E1) | after each story job: a followed source's linked page (always on); with **Collect originals** (`collect_originals`, on by default): a News story's original page, an entity's original (2+ voices made it the subject in 7 days), curated long-reads' cited pages, a followed source's page another source linked, Classics; one shared credit (1% of the schedule's fetches, ≤3 at once); every ask recorded in `story_originals` | the "pages 2+ sources link" step joins it as one more planner (kind `cited`) |
| `db/repo_linked.linked_not_stored` (0084 B) | per **followed** source: its own pages your posts link that are not stored (Archive's count, the fetch job, 0114's wanted links) | unchanged; it covers followed sources' pages only — `cited` covers the pages of sites you don't follow |
| `services/follow_archive.py` (0167) | following a feed fetches its archive back to the reading window | the backfill after an auto-follow |
| 0093 (future) | noise per source | the item filter is its first concrete part |

Nothing today adds a source by itself, and nothing hides an item of a followed source.

## Measured (2026-11-13)

**Data.** A scratch clone of the v10.16 anchors copy (the 2026-11-05 server export with Mark X stories, read-v2
readings, 8,843 entities, 1,031 entity addresses; no read-v3), dropped afterwards; 59 read-only calls to the server
(53 `find-feed`, 6 `page-watch/preview`, one at a time); the GitHub API for 18 public release feeds (newest 100
each); Haiku through `claude -p` exactly as the worker calls it (67 web-search lookups, 18 filter proposals);
`insight_ru_show` read-only for linked pages.

### 1. Do the stories hold the official post? (171 announced-type stories, Oct 6 - Nov 5, labelled by hand)

| | count | share |
|---|---|---|
| stories whose readings say announced more than reported | 171 | |
| ... commentary, third-party tests, essays (no own announcement) | 39 | |
| ... a filing (policy_legal) | 1 | |
| **events an actor announces itself** | **131** | |
| the actor's own post is in the story | 64 | 49% |
| it is not | 67 | 51% |
| ... the story links an own page of the actor's | 31 | |
| ... only junk own pages (docs, help, CDN, a product or pricing page, a look-alike domain) | 7 | |
| ... no own link at all | 29 | |

The 67, after the lookup and the proof below:

| Outcome | events | share of the 131 |
|---|---|---|
| a followed source already holds or covers it (a story split, a follow made after the event, the official post on a followed X account) | 15 | 11% |
| a new site section proven (a feed, or page watching that reads dated articles; 3 carry the event's own page) | 15 | 11% |
| a new GitHub releases feed proven | 9 | 7% |
| a new X account, its stream proved only by the first read | 16 | 12% |
| no channel the finder or page watching can prove (repos without releases, a one-off page, a home page with no section) | 11 | 8% |
| the lookup named the wrong actor | 1 | 1% |

So with the module on, 64 + 15 (the join/backfill fixes, which are ingestion's and Mark X's, not a new follow) + 40
new channels would put the official post within reach of **119 of 131 (91%)** events, against 64 (49%) today. Of
the 40 new, 24 are proven by the finder or page watching now; 16 (X accounts) only by their first read. 11 (8%) have
no provable channel: the story says "official source not found" (not "no official source", which is for lawsuits,
regulators and scoops).

### 2. Who and where, by web search (Haiku with Claude's WebSearch, guide `official-v0`, at most 4 searches)

All 67 events lacking their official post, given the event's headline, up to 3 posts and the things named (no maker):

| | result |
|---|---|
| the actor right | **64/67 (95.5%)**; wrong: a layoffs story given another bank; a story mixing two labs' plan limits (it answered the headline's); a small app whose repository differs from the one the post links |
| channel addresses proposed | 199: X account 57, site section 45, repository 30, site root 29, one page 14, code-host org 12, model-hub page 9, a post 2, video channel 1 |
| with a channel's shape (account, section, repository) | 132 (66%); the rest are cut by code before any proof |
| an employee's personal account offered as official | 2 of 67 answers (code can't tell; the proof's ownership rule refuses a handle that isn't the actor's name) |
| cost | **$0.035 a lookup** (min $0.025, max $0.061), 3-5 turns, 14-45 s |

It also said "not official" for four third-party tests: right for the post, but the thing tested still has a maker
with a channel. The module asks for the maker of the **thing**, not of the post.

### 3. The would-add list (71 distinct channels after code shape, ownership and not-followed; read blind)

| | official | official-and-wanted |
|---|---|---|
| a uniform 40 of the raw would-adds | 37/40 (92%) | **20/40 (50%)** |
| all 71 | 65 (92%) | 36 (51%) |
| after code gates: a repository must have releases; the actor has 2+ announced events in 30 days or the event 3+ voices; one section a site | 38/39 (97%) | **29/39 (74%)** |

Why not wanted, in the uniform 40: off-topic for this reader 9 (a car maker's three press channels, a language's
release feeds, a certificate company), a repository without releases 4, a one-off project 2, wrong actor 2, a small
project 2, a conflict 1. After the code gates what stays wrong is off-topic (5: the reader's fit, which 0173's
`fits` measured 19/20 right in E8), the whole forum instead of its announcements category, a reference repository not
the event's thing, a help centre, a company's main X account (mostly consumer posts). **The bar (95%) is not met by
code alone**: the fit judgement and three shape rules are needed, and Shadow measures them (below).

### 4. Proving a channel (59 server calls)

| Candidate | finder / page watching |
|---|---|
| X accounts (16) | 16 "found": the bridge address is built, `holds` 0 — **no proof**; the proof is the first read (posts, dated, the account's own) |
| repositories (14) | 8 releases feeds; 6 none — exactly the repositories with no releases (checked on the GitHub API) |
| site sections (19) | 8 feeds (a lab's news feed holds 14 pages your sources link; a research blog 13; a developers' blog 27); page watching proved 3 of 6 more (359, 111, 10 articles found; two of them list the event's own post); 2 found pages but read none; 1 nothing |
| junk starts (7: a docs site, an app studio, a CDN path, a help centre, a product page, a look-alike domain) | none — the finder already refuses them; the 0170 rows that show them are rows the module would never write |

### 5. Release feeds: noise and the filter (18 public repositories, newest 100 releases each)

| Feed shape | items a day | hidden by the learned rule |
|---|---|---|
| inference engine with per-commit builds | 16.3 | 99% (`^b\d+$`) — shown 0.2 a day, its v1.0 among them |
| coding agent CLI with alphas | 2.3 | 84% (`-alpha.N` + the prerelease flag) |
| agent CLI with nightlies and previews | 0.87 | 85% |
| editor with `-pre` builds | 0.50 | 47% |
| a framework releasing per package | 1.0 | 0% (each package's release is real) |
| 12 others (SDKs, libraries, apps) | 0.03-0.73 | 0-8% |
| **all 18, 30 days** | 300 items | **152 hidden** |

The rule was proposed by Haiku from each feed's **older** items (31-80) and applied by code to its newest 30
(held out): **real releases hidden 0/417, builds shown 0/49, pre-releases hidden 41/42** (one rc shown: the model set
no flag rule on a feed with one rc in 50). A project whose every release carries "-beta" (and no prerelease flag)
was read as releases, rightly. $0.0009-0.0018 a channel, once.

### 6. Pages 2+ sources link (local copy of 249 sources, 29 Oct - 5 Nov, 1,345 posts)

| | count |
|---|---|
| distinct link targets | 3,840 (kind `link`, not boilerplate) |
| linked by 2+ voices (voice = the source's voice, else the source) | 85 a week (68 ×2, 14 ×3, 3 ×4+) |
| ... already stored | 14 |
| ... classes of the 85 | page 21, repository/model card 16, stored 14, a tweet 12, front page 8, video/music 5, pricing/help/docs/README 5, paper 4 |
| ... one publisher counted twice (a publication's two feeds; one text cross-posted by two channels) | ~12 (14%) |

Read 30 (not stored, uniform): **the true origin of what was reported 14/30** (an announcement, a paper, the original
report, a primary statement or document; 5 of them tweets), a release artifact (repository, model card) 8/30, **not
an origin 8/30** (a front page, a stream video, a repository cited as a reference, a README, a pricing page, a side
project's app, a leaderboard cited in a dispute). With the exclusions below (front pages, media, references, pricing,
help, README; tweets read only from quotes; repositories and model cards left to 0138's entity originals) 11 of the
30 remain: **9 origins, 2 not** (82%; the classes applied by hand to the 30, not run as code).

## Design it twice

**A. A channel book per actor (chosen).** One deep module keyed on the **actor**: an event without its official post
asks "who is the actor and which of its channels are proven"; the answer (channels, proof, filter) is kept per actor
and reused by every later event of that actor. Candidates from the story's links, the thing's addresses (0138), the
actor's handles (0168), and the worker's web search only when those give nothing.

**B. Auto-follow 0170's rows.** Keep 0170 per event: when a story lacks its main source and its links name an own
page, follow the channel the row tested.

| | A. channel book per actor | B. 0170's rows, followed |
|---|---|---|
| events with no own link (29 of 67) | web search, once an actor | never (0170 needs a linked own page) |
| junk own pages (7 of 67 here; ~35% of 0170's server rows, the coordinator's count) | refused by proof (owned + dated stream + a channel's shape) | the same junk, now followed |
| repositories → releases + their noise | releases from 0138's code address, item filter on add | no releases path; builds flood |
| calls | one lookup an actor (36 actors for 67 events in 30 days), cached | one finder test an event |
| "already followed" (15 of 67) | detected: the actor's channel is followed → the join or backfill is the fix, no new source | 0170's coverage, the same |
| the maker | written back through identity's one owner | none |
| what Discover shows | the module's channel book (would-add, added, undone, refused and why) | unchanged |

**A is chosen**: it reaches the 29 events with no own link, refuses the junk class by proof instead of by list,
handles release noise, costs a lookup per actor rather than per event, and makes 0170 a view of it instead of a second
place that decides channels.

## The design (A): `markx/official.py` — Official channels

### Interface (three entry points)

```python
# markx/official.py — Official channels
def run(cur, now, *, budget, ask) -> RunCounts:
    """The jobs process's pass (bounded): the events of the last WITHIN_DAYS without their official post, each
    actor's channel book brought up to date (candidates, proof, filter), adds made (or recorded, in Shadow),
    answers applied. Resumes where the last pass stopped."""

def book(cur, actor_ids) -> Dict[str, ChannelBook]:
    """Every reader (Discover, the story's "original", the entity page): {actor: channels [{key, kind, follow,
    state: candidate|proven|would_add|added|undone|refused|covered, why, evidence, filter}]}, one query."""

def pages_wanted(cur, now, *, limit) -> List[PageAsk]:
    """For the originals step: the pages 2+ voices link (and an official channel's pages, one voice), not stored,
    not asked, that pass the exclusions. OriginalsService reads them under its credit."""
```

Inside: the actor rule, the candidate sources, the proof, the gates, the item filter's proposal, the add, the undo.

### 1. Which events

0170's selection, moved here: current Mark X stories first seen in WITHIN_DAYS (30), an announced type through the
event-type seam (`event_types.ANNOUNCED`); **one voice is enough** (the trigger was a single forum post). Never
`policy_legal`, `leak_rumour`, commentary, a digest, a tutorial: those show **"no official source"** on the story.
An event whose actor's own post is a member: nothing to do.

### 2. The actor

In order, the first that answers: the story's maker by identity (0184 `entity_facts.read(...).maker`; until then
`perspectives.Story.maker`); the org/person half the members name as actor (`named_actor`, 0170); the **maker of the
thing** the event is about (a product's maker fact); else a `websearch` question (guide `websearch-official-v1`, the
same kind as 0171, priority -1): the event's headline, up to 3 posts, the things named, the actor INSIGHT guesses (or
"unknown"); answer `{actor {name, site, kind}, announcement {url, why} | null, channels [{url, kind, why}] (≤4),
official: bool, why_not}`. One question an actor-thing pair; the answer is kept and reused.

**The maker found is written once, through identity.** `entity_facts.set_maker(thing, maker, by='web', evidence)` is
0184's API; until 0184 lands the same function (in `markx/identity.py`, one owner) fills `mx_entities.maker` **only
when it is NULL** and records the evidence on the channel row; the owner's or the mentions' maker always wins. No
other table holds a maker.

### 3. Candidates (no call first)

- the story's own pages of the actor (0170's `_own_pages`, `owned_by`) → their channel (`channel_of`);
- the thing's code address (0138 `code`) → `<repo>/releases.atom`; its release address's site section;
- the actor's handles (0168 learned pairs, its own sources' accounts) → the X / Telegram account;
- only when these give no proven channel: the web search's channels.

Cut by shape before any request: a site's root (who, not where), one page that is not a section, a code-host or
model-hub org page, a status (a post), docs/help/support/CDN/download/pricing/product pages (0170's
`PLACE_TESTS` and LEGAL, plus `help.`, `support.`, `docs.`, `cdn.` hosts), a forum's root (keep its category path).

### 4. Proof (code; all three, else not a channel)

1. **Owned by the actor:** the channel's registrable name, handle or code-host owner is one of the actor's names or
   handle forms (`owned_by`), or the actor's site as the web search gave it, or a thing the actor makes; an employee's
   account is not the actor's. A disagreement (the post links one repository, the search names another) is refused.
2. **A dated stream:** the finder found a feed, or page watching reads 3+ dated articles under the prefix, or the
   account's first read gives 3+ dated posts of its own (X, Telegram: 0170's `test_channel` through the source kind).
3. **Carries announcements:** the feed or page holds the event's own page (`holds`) or another announced-type post of
   the actor in 90 days; a releases feed carries a release (after the filter).

Plus **not covered**: an enabled source on the channel (0170's `covers`) means the gap is a join, a section or a
backfill: the module records `covered` and the matching fix (0170's `wrong_section`, 0167's backfill), never a new
source.

### 5. Wanted (the gates measured in 3)

- the actor has 2+ announced events in 30 days, or the event 3+ voices (code);
- one channel of a kind a site; an X account and a site section may both be kept;
- **fits the reader:** one `source_judge` call (0173) on the proven channel: `verdict follow` and `fits` true; its
  rewriter marks and health are code's. Skip → `refused` with its reasons (shown in Discover, never asked again for 90
  days).

### 6. The item filter (per source, applied by code)

The same `source_judge` call returns, for a channel with 10+ items (guide `source-judge-v2`, a new field):
`filter {kind: releases|builds|mixed, hide: [{field: tag|title, regex, why}] (≤4), hide_prerelease_flag: bool}`.
Server checks (`validate`): each regex compiles, is on a shape (no literal version), matches at most 95% and at least
one of the items shown, and the shown examples are not hidden by it.

- Stored as a row (`source_filters`: id, source_id, rule jsonb, by `worker`|`owner`, guide, call_id, created_at,
  superseded_at); the current row is copied into `sources.settings.item_filter` for ingestion.
- Applied by code at store time (ingestion's one insert path): a matching item is stored as any post and marked
  `posts.filtered_by` = the filter row; the feed, News, stories, digests and unread counts skip it (`filtered_by IS
  NULL`, a partial index). Its source's page shows "N hidden builds · show". **Nothing is deleted**; changing or
  undoing a filter re-marks that source's posts (a job, not the request).
- GitHub feeds: the prerelease flag is not in the Atom feed; the fetcher reads it from the releases API for a
  `github.com/<o>/<r>/releases.atom` source (one request a fetch, its own host gate), else the rule uses titles only.
- Any source may have one (0093's first part); the owner can edit it on the source's page.

### 7. Follow (Shadow, then on)

- **Shadow** (`INSIGHT_OFFICIAL=shadow`, the default after deploy): every proven, wanted channel is recorded
  `would_add` with its evidence, its filter, and what it would have held (the event's page). Discover's "The main
  source is missing" shows the module's rows: would add / covered / refused, with the evidence.
- **On** (`INSIGHT_OFFICIAL=on`, after the bar): the add goes through the add path every add uses (the finder's
  feed, else page watching's prefix; `sources_service.add_source`), settings `{added_by: "official", official: {actor,
  channel row}}` and the item filter. Then 0167's archive backfill (`follow_archive.queue_on_follow`), so the
  event's own post is fetched and joins the story (backdated items join, 0167); Mark IX's origin and Mark X's
  `attach` show it as the story's **original**.
- Shown everywhere as **"added automatically"** (the source row, the feed's byline, Discover) with one tap
  **Undo**: the source is turned off (its posts kept), the row becomes `undone`, and that channel is never added again
  by the module. At most ADD_PER_DAY (5) adds a day; above it they wait as `would_add`.
- **Never non-official**: a channel without the three proofs is never added, whatever its quality.

### 8. Pages 2+ sources link (the `cited` planner, inside the originals step)

`pages_wanted` gives OriginalsService one more plan, after `collect` and `entity`, under the same credit and the same
reader (the save path's), recorded in `story_originals` (kind `cited`), Collect originals' switch:

- **qualifies:** a page 2+ voices link in 7 days (`voice.count` with `STORIES_IX`: a publication's feeds one voice,
  copies of one text one, a Telegram forward one); or a story's main post's target (0123's, already); or **a page on a
  proven official channel, one voice**.
- **excluded:** stored or asked; a front page (`E.front_page`); Discover's no-source places (references, docs, apps,
  archives, documents: `discover_rules`), pricing/legal/help/README/blob pages, media hosts (video, music, streams), a
  code host's or model hub's repository home (an artifact: 0138's entity originals read those already), a tweet (from
  a quote only, 0123), a followed source's page (0114 / `linked_not_stored` own it).
- **stored:** the page's text as a post of the Saved source (0122's path, `collected_as: cited`); its HTML only when it
  becomes a story's original. Read by the worker's `read` like any new post.
- `linked_not_stored` is unchanged (followed sources' own pages); `cited` is the same idea for sites you don't follow,
  and the `missed` planner (F2) stays the followed-source case. One owner per page kind, one credit.

### Where it runs

The jobs process (`markx/jobs.py`), a job `official` in its own child process after each decision run and every
EVERY seconds, never in the API: at most EVENTS_PER_RUN (20) events, FINDER_PER_RUN (10) finder or preview calls
(`FEED_FINDER_HTTP`'s own client and AddressGuard), 1 open `websearch` question per actor, its state in Postgres
(`mx_official_channels`, `mx_official_runs`: a cursor, keep everything). The API only reads `book()` (one query by the
actor ids a page holds). The `cited` fetches run in ingestion's originals step, under its existing credit.

### Rows (migration 0134+)

`mx_official_channels`: id, actor_id, key, kind (`x`|`telegram`|`section`|`releases`), follow, state, why, evidence
jsonb (the candidate's origin, owned-by, the finder's or the first read's answer, holds), judge_id (0173), filter_id,
source_id, events (story ids), created_at, decided_at, superseded_by. A new state is a new row (keep everything).
`source_filters` and `posts.filtered_by` (above). `story_originals.kind` may be `cited`.

## Cost

| | a day (server, ~3× the local copy) |
|---|---|
| web-search lookups (events with no own link or only junk: 36 in 30 days locally, one an actor) | ~3-4 × $0.035 ≈ **$0.13** |
| `source_judge` + filter (one a proven channel; ~39 in 30 days locally) | ~4 × $0.003 ≈ $0.01 |
| finder / preview requests | ≤ 10 a pass, ~30-60 a day |
| `cited` pages (85 a week locally → ~120 a day on the server before exclusions; ~37% after: 11 of 30) | ~40 fetches, ~0.4 MB text, `read` at ~$0.002 a post ≈ **$0.08** |
| total worker | **≈ $0.25 a day**, under 1% of the worker's ~$43 a day (0191) |
| memory | API: one indexed query a page; jobs child: the window's announced stories (0170's `pick`, already run for Discover) and `identity.lazy_book`; no book load |

## Dependencies on 0184

- **Not blocking.** The actor comes from 0170's rule today; 0184's facts replace `perspectives.Story.maker` and the
  stated-maker strings when they land (one call site, `official._actor`).
- **One maker owner.** The web search's maker goes through `entity_facts.set_maker` (0184's interface); until 0184,
  that function is a thin shim in identity that fills a NULL `mx_entities.maker` and nothing else. When 0184 lands
  the shim becomes a facts row `by='web'`, ranked below the owner's and the mentions' makers.
- **Bare names.** A thing whose name is a bare key in 0184's sense (several senses) gets no web search until its sense
  is placed: otherwise the search could tie a channel to the wrong sense.
- **35% of products lack a maker** (0184's census): those are exactly the events that need the web search; 0184's
  maker consolidation (no call) shrinks them first, and the module's lookups fill the rest.

## The bar for switching on

Shadow for two weeks on the server, then:

| What | Bar |
|---|---|
| would-adds, a uniform 40 read blind (official and wanted for this reader) | **≥ 95%** (38/40) |
| non-official channels added | 0 |
| an added channel's events: its official post now in the story (the backfill and the join) | ≥ 80% |
| item filter on the channels added: a real release hidden | 0; builds shown ≤ 5% |
| web-search actor right (the 40's events) | ≥ 95% |
| `cited` pages, 30 read: the true origin of what was reported | ≥ 85% (82% by hand today); tweets and front pages 0 |
| cost a day (worker log) | ≤ $1 |

Measured today: official 92%, official-and-wanted 50% raw / 74% with the code gates; the fit judgement, the
forum/help/reference shape rules and the actor's main-account noise are what Shadow must show close the gap. Then
the realdata-check on main and the reader review, before the owner switches it on.

## Test plan (invented names; stubbed requests; the stage on a test database)

1. A forum post with no links about "<Engine> v1.0": no own link → one `websearch` question; its answer names the
   org and `github.com/<org>/<engine>`; the finder (stubbed) finds `releases.atom`; ownership by the code-host owner;
   10 items `b1001..b1009` and `v1.0.0`; the filter `^b\d+$`; Shadow records `would_add`; on: one source added with
   the filter, the archive queued, `v1.0.0` shown, the builds stored with `filtered_by` and absent from the feed.
2. A lab's model release whose story links `<lab>.ai/news/<slug>`: the section `/news/`, the finder's feed holds the
   page → proven, added; the event's page joins the story as its original after the backfill.
3. The same lab already followed at `/news/`: `covered`, no source added; the story's missing member is reported as
   a join.
4. A lawsuit against the lab: no lookup; the story says "no official source".
5. Junk own pages (a docs page, a help article, a CDN path, a pricing page): cut by shape, no request.
6. A repository without releases: the finder's none → not a channel.
7. An employee's X account offered by the search: refused (not the actor's name); the lab's own account kept.
8. The post links one repository, the search names another: refused, said why.
9. An off-topic official channel (a car maker's press feed): `source_judge` skip → `refused`, asked again after 90
   days only.
10. Undo: the source off, posts kept, the row `undone`; the next pass never re-adds it.
11. ADD_PER_DAY: the sixth proven channel of a day waits as `would_add`.
12. The maker: the search names the maker of a makerless product → `mx_entities.maker` filled once (shim); a product
    with a maker keeps it; no other table written.
13. The filter's checks: a regex matching everything, a literal version, one that hides a shown example: refused.
14. `cited`: a page linked by two voices → planned; by one publication's two feeds → not; a front page, a video, a
    pricing page, a README, a tweet → not; a followed source's page → `linked_not_stored`'s, not `cited`.
15. The API: `book()` is one query (counted), no book load; the job is bounded by its budgets.

## Not measured (say so before relying on it)

- X accounts' proof: the bridge address is built, the first read's posts were not fetched here (16 of 40 new
  channels depend on it).
- The fit judgement on these channels (0173's E8 measured `fits` on other spheres: 19/20 out, 0/45 in called out).
- The server's own rate of events lacking their official post (the census is the local copy's 30 days; the server is
  ~3× larger).
- Page watching on the two sections that found pages but read no article (likely built with JavaScript).
- `cited`'s exclusions applied as code (the 2-of-30 estimate is the classes applied by hand to the 30 read).
