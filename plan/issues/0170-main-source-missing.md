# 0170 — Discover: the main source is missing (spec + built)

INSIGHT v10.15, part D. Evidence: plan/research/exp-2026-11-12/e5e7 (REPORT.md, appendix_e5.md: exact rows; private,
gitignored). Names below are invented.

## The problem

Of company and person events with 2+ posts, 53–65% hold no post from the actor's own channel (local census 76/144,
server sample 49/76). The event's own links point to the actor's main post in 59 of 76. Following the channel the feed
finder or page watching found would have held the post in ~47% of them (36/76; up to 52/76). Discover suggested sites
your sources keep linking, but never "the maker's own post of this event isn't in INSIGHT: follow its channel", and it
ran the finder on a site's home page, where it found nothing for sections that page watching reads (a /blog/, /news/
section; a subdomain of the maker's).

## What to build

1. For each Mark X story with 2+ voices whose actor (org or person subject, or actor entity) has no post from its own
   channel in the story: when the story's posts link a page on the actor's own site or section, or the actor's
   platform account (0138 entity addresses and the posts' links), suggest following that channel. Never for lawsuits,
   regulator actions, scoops or filings: read-v3 event types and the readings' actors decide, no word lists.
2. The finder runs on the main post's SECTION (the path prefix of the linked own page), not the site's home page;
   page watching's preview with that prefix when the finder finds no feed. Every add goes through the existing add
   path (Add source: the feed finder, then page watching) when the owner taps.
3. Followed but the wrong section: a followed site whose feed or page watch misses the event's page (launches at the
   site's root while the watch covers /news/; /news/ vs /blog/; a subdomain): a second section for the same site.
4. Followed but disabled: a turned-off source that was the event's main source is surfaced.
5. Shown in Discover with the evidence: the event, its posts, the own page they link, what the finder/preview found.

## Built (Stealth v10.15, branch `v1015-main-source`)

- `services/discover_main_source.py` (new; the rules in its docstring), `routers/discover_main_source.py` (new, one
  include line in main.py): `GET /api/discover/main-source` → `{rows, total, checked, events, within_days}`. No
  migration: the follow tests are kept in system_settings `discover_main_source`.
- **Which events.** Current, unmerged stories of 2+ voices first seen in the last 30 days, whose story type
  (`built.event_type` over read-v3) is one an actor announces itself: model, product and research releases, business
  events, incidents, public statements, promotions. Never `policy_legal` (lawsuits, regulators, filings) nor
  `leak_rumour` (scoops, leaks), nor commentary, digests and tutorials; a story with no read-v3 reading is not flagged.
- **The actor.** The story's maker by identity (perspectives.Story.maker), else the org or person half its members or
  more name as subject or actor. The readings must name it as the event's: the first of a reading's main actors once
  or more, and among the main actors in half the readings or more (`named_actor`). This drops an outlet cited beside
  the actors ("…, an outlet reports") and a site the members only talk about.
- **Its own page.** A page the members carry whose owner is one of the actor's names or a thing it makes (a site by its
  registrable name, a hosting platform's writer by theirs, an X handle; `<product>.ai` and `@<product>ai` of the
  product's maker), or an 0138 address (release, work) of the actor or of a thing it makes. It counts as the event's
  own post when it is a member's own address (held by an aggregator or a repost), 2+ members link it, it is a short
  link post's main link, it is the story's source page, or it is a post on X. Code hosts, model hubs, platforms,
  Discover's no-source places (references and docs, papers, records, apps, files) and product, pricing and legal
  pages are no channel; a home page is none either.
- **The channel.** An X post: the account; a Telegram post: the channel; a site's page: its section (`/blog/`,
  `/newsroom/` for a dated path, `/en/blog/` after a language), the site's root for a page at the root. One channel an
  event, its best evidenced page's.
- **The verdicts.** A member from the actor's channel (its source's name names the actor, or it is the account, or a
  site source on the channel's site): no row. Else no source on the channel: `missing`. An enabled source covering the
  page (an account; a page watch whose prefix the page is under; a feed holding posts in the page's section, or none
  yet): no row for the whole event (stored under an aggregator, or published before the follow: ingestion's).
  Only a disabled source covering it: `disabled`. Enabled sources on the site, none covering it: `wrong_section`, a
  second section. A disabled source named for the actor (a subreddit, "<Actor> blog"): `disabled` beside.
- **The test.** Opening Discover tests at most 8 shown channels not tested in 30 days, in the background, as
  Discover's follow test: an account through its source kind; a section through `where_linked.follow` on the section
  with the events' own pages as the linked articles (`holds`: how many a feed or page keeps), then
  `page_watch.preview(section, prefix)` when it found neither a feed nor a page. Off with INSIGHT_DISCOVER_READS=0.
- **Discover.** Sources tab, above the archive rows: "The main source is missing" (components/sources/
  MainSourceMissing.tsx, lib/mainSource.ts): each row its channel, the actor (its entity page), why, what the test
  found, the events behind a fold (headline → the Mark X story, type, sources, the own page and how the event carries
  it, its posts). Follow… / Follow this section… open Add source on the channel; a disabled source has Turn on; Not
  interested hides the row (`main:<channel key>` in discover_hidden).
- Reads Mark X's tables only (a test proves their checksums unchanged); no post or derived row is written or deleted.

### Measured before adopting

A read-only run on the local census copy (Oct 5 – Nov 5, 141 stories of 2+ voices; it has no read-v3, so every type
was let through): 18 events flagged in 17 rows (14 missing, 2 wrong section, 1 disabled), 16 plausible by E5's rows
(the maker's X account or blog, a subdomain of a followed site, an engineering section beside a followed /news/, a
turned-off subreddit). Wrong: an outlet as the actor (1, a business story; the type gate decides on the server), a
model-card section (1). Rules changed by this run, each a class: the readings' main actors decide the actor (removed
outlets, a platform and sites the members only cite: 28 rows became 16), a site's owner by its registrable name (a
hosting platform's writer was read as the platform), product names as the maker's (a product's own site and X
account), product/pricing/legal and Discover's reference pages are no channel, one channel an event. 0.6 s a scan.

### Tests

backend `insight_core.tests.test_discover_main_source` (29: channels, coverage, verdicts, the actor rule, the page
and the test with a fake finder; the scan on a _test database: missing, never for policy_legal or leak_rumour, a
second section and a watch covering it, a disabled source, the route and a hidden row, Mark X untouched). Frontend
`mainSourceMissing.test.tsx` (6), the design frames' Discover fixtures carry the route.

## After deploy: how to measure

- **Suggestions per week:** rows' events by `first_at` week (`GET /api/discover/main-source?limit=100&test=false`,
  `events[].first_at`), and rows per kind.
- **Precision, 40 read:** 40 events drawn uniformly from the rows; each labelled right (the own page is the actor's
  main post of that event and the channel is the actor's), wrong (with the class: actor, page, type) or n/a; in the
  report-breakage format (event → own page → channel → label).
- **Would have held the main post:** for each tested channel, `test.holds` of `test.of` (a feed or page found keeps
  the event's own page), and for `page` labels via the preview, whether the page is under the preview's prefix; the
  share of the 40 whose channel, followed, holds the main post. E5's bar: ~47% of the events lacking their channel.
