# 0080 — Discover that reads well: tested suggestions, real names and titles, owners not platforms

Status: **spec, decided** (owner, 2026-11-04: "80 everything recommended"), written 2026-11-04 from a read of the server's Discover (owner: "does very bad discovering"). Planned for v9.17, after 0076 and 0077. It starts after 0072 A merges, because that branch holds `stories_service`'s Discover code. Builds on 0050, 0060, 0065 and 0067.

**Constraints:** no real source names in this file or fixtures; measure on a copy of the lab and on a fresh server copy; nothing merges unless `scripts/realdata-check.sh` passes.

## The case (the server, 2026-11-04; the data is kept privately in `plan/research/discover-prod/`)

| What | Count |
|---|---|
| suggestions | 1,122: 632 sites, 478 X accounts, the rest platform accounts |
| that start none of your stories and hold no classic | 1,019 |
| names of the sources linking them that are a feed address (`https://…/feeds/main`) | 1,411, in 609 suggestions |
| article lines shown as a bare address | 3,908 of 10,682 |
| article titles rebuilt from the address's words ("Ai jobs white collar unemployment …") | 3,982 |
| whole platforms suggested as one site, including **#1 and #2** (a model hub, a preprint server), a blog platform, a Mastodon server, a creators' platform | 5 |
| help, docs and support sites (`help.…`, `support.…`, `docs.…`) | 7 |
| a site you already follow suggested again, because some of its pages are outside your feed | 2 |

**Tested from this machine** (the top 60 sites, and the first article of the top 80 suggestions):
- 10 sites refuse plain readers (HTTP 401 or 403), including 6 of the top 40: a wire service, two business papers, a paywalled tech newsletter, a news site, and the help site of a source you follow;
- 2 refuse with HTTP 400 or 406, and 1 article answers 402 (a paywall);
- 18 home pages announce no feed.

Discover tests nothing, so it can't tell "follow this" from "you'll only ever get headlines".

## Why it reads this badly (causes, not symptoms)
1. **Discover counts, it doesn't check.**
   - A suggestion is "3+ of your sources link it" (0050).
   - Whether it can be followed, what it is (a publication, a platform, a help centre) and whether it is readable were never asked: "fetches nothing" was a rule.
2. **Every fallback leaks onto the page.**
   - A source with no name shows its address (`SourceFacts.voice_name` returns `sources.name`, which the importer filled with the feed address).
   - An article with no stored post and no link words gets its address's slug in title case (`origin_title`), or the bare address.
   - Each fallback was a sensible last resort, but nothing counts how often the last resort is what's shown: here it is 74%.
3. **The unit is the host.**
   - That's right for a publication. It's wrong for a platform, whose host holds pages from many owners: there the owner is the source (0060 did it for X, GitHub and YouTube from a fixed list of platforms, `DISCOVER_PLATFORMS`).
4. **No size limit.** Every candidate is listed. 0067 cleaned what shouldn't be there, but nothing limits what's shown first.
5. **It was never reviewed on production data.**
   - 0067 was judged on the lab (30 Oct).
   - The reader review covers stories, News and the feed more than Discover.
   - 0075's invariants check Discover's titles against the feed's, not whether a name or title is an address.

## Decided (owner, 2026-11-04: every recommendation, including the first page of about 30 and the follow test's requests)
1. **One name for a source, everywhere.**
   - A source's display name is its own name, else its feed's or site's title, else its host (`example.com`), and never an address.
   - It's one function, used by the feed, stories, News, Classics, Discover and source health (the class of 0072 D1's titles).
   - Measure how many sources it renames.
2. **One title for a linked page.** In order:
   1. the stored post's title;
   2. the link's own words, when they are a title (not "here" or "link");
   3. the page's title, read once and stored for the top suggestions' articles only (see 4);
   4. otherwise, the line shows the site and section (`example.com · blog`) and no title.

   A bare address and a title rebuilt from the address's words are never shown.
3. **Owners, not platforms, from the data:**
   - a host is a platform when the pages your sources link there have **many different first path segments, each linked by different voices**;
   - its suggestions are those owners (`hub.example/org`, `forge.example/team`, `social.example/@user`);
   - measure the threshold on the lab, and check it on hosts nobody named;
   - `DISCOVER_PLATFORMS` stays only as long as the measured rule needs it.
4. **Test what's shown, then label it:**
   - for the suggestions on the first page, run the feed finder (the same path every source add takes: the feed finder, then page watching) once, and store the answer with a date;
   - labels:
     - **Feed found**;
     - **Page watching**;
     - **Headlines only** (a paywall, or no feed and a walled page);
     - **Blocks readers** (401 or 403 on every way of reading the finder knows);
   - "Blocks readers" and "Headlines only" sink below every followable suggestion and say so;
   - this changes Discover's "fetches nothing" rule: a few small requests, only for what's shown, never repeated within 30 days.
5. **References aren't sources.**
   - Help, docs, support, status and government pages are linked as references: their pages aren't dated articles.
   - Decide by what the links are (pages with no date, or stable URLs linked again and again), not by a list of subdomains; measure it.
   - They go to a quiet "References your sources use" line, never into the suggestions.
6. **A site you follow is never suggested.** Pages of it outside your feeds go to "missing from a source you follow" (0065's archives).
7. **Fewer, ranked, each with its reason:**
   - the first page holds about 30;
   - rank by:
     - the stories it started;
     - its classics;
     - how recently your sources linked it;
     - how much you open what they link there;
     - whether it's followable;
   - the rest behind "More";
   - X accounts stay (owner, 0067: "sorted by impact, priority and sourced by") and are ranked by the same signals, not apart;
   - an X account's lines show its stored tweet's text, never a status address.

8. **A source's health says what failed, and waits as long as the error deserves** (moved to [0088](0088-v9.16-backoff-health-and-rail-order.md), 2026-11-04; moved here from 0081, owner 2026-11-04; the case: a feed service answering 502 put a source into a 6-day wait):
   - a 5xx is the other server's trouble, so retry within hours, never days;
   - the health text names the site, not "the server": "example.org is failing (HTTP 502): its own server didn't answer, usually temporary."
   - Files: the fetch backoff and the health text (ingestion and source health), not Discover's. This is its own slice.

9. **From the v9.15 reader review (2026-11-04):**
   - Discover sends 1.96 MB per open and draws all 1,070 suggestions at once: the first page's answer carries only that page;
   - Reddit authors inflate "linked by N of your sources": count followed sources there, as 0067's wording says;
   - the Saved source counts as a source on 5 suggestions: it never does.

## Invariants added to 0075's check (each on every suggestion of the copy)
- No source name, voice name or article title is an address.
- No article title is its address's slug in title case.
- No suggestion is a host you follow.
- The first page holds at most 30, and each says why it is there.
- Every first-page suggestion has a follow test no older than 30 days.

## Measured before adopting
- The renamed sources (1).
- The titles by where they came from (2): the share of "no title" must be reported, not hidden.
- The platforms found (3), checked by hand on 20, and on hosts nobody named.
- The labels (4) on the first 60.
- Discover's answer time with the stored tests.

## Measured (2026-11-04, a copy of the lab and the server's saved answer; details private in `plan/research/0080-measure/`)
What the numbers change in the decisions above. Where they differ, **this section wins**.
1. **Names:**
   - 88 of 247 lab sources are named by their feed address (importer, no display name); 62 sources on the server.
   - No feed or site title is stored, so the fallback is the host.
   - The screen already makes address names readable (`frontend/src/lib/sourceLabel.ts`), so the addresses show in API answers, not on Discover's screen. The fix belongs in the backend's one name, built in 18 places today.
   - **Changed:**
     - the host fallback keeps the owner when the address is a multi-owner host (`newsletter.example/author`, `~user`, an author feed);
     - it drops feed-only subdomains (`feed.`);
     - two sources that would share a host keep their sections (`example.com/news` and `example.com/research`).
2. **Titles:**
   - 37% of article lines show a bare address and 37% a title rebuilt from the address.
   - Without reading page titles, 75% of all lines (87% of site lines) would show no title, so **reading the page title once, for the first page's articles, is required, not optional.**
   - An X line has its stored tweet only ~15% of the time, so otherwise it reads "a post by @account", never a status address.
3. **Platforms:**
   - **The rule:** a host is a platform when it has 50+ owner segments (or 15+ with none above 20% of the pages), and 2+ owners are each linked by 2+ voices. Numbers, dates, ids and language codes aren't owners; a 70%+ prefix (`/r/`) moves to the next segment.
   - **Results:** it finds 10 of 1,313 hosts, including two nobody named. It is debatable on a contributor-network magazine and a store.
   - **Added:**
     - the owner may sit at the third segment (a blog platform's company blogs);
     - a link from a source to its own page on a platform doesn't count (a creators' platform suggested from its own creators);
     - a host whose addresses hold paper ids and no owner (a preprint server) is a **paper source**, not a site: its papers stay in Classics and stories, and it is never a suggestion.
   - `DISCOVER_PLATFORMS` stays for video and Telegram, whose addresses the rule can't read.
4. **References:**
   - The data argues against "decide by what the links are": undated, re-linked pages are mostly ordinary blogs (44 hits, 0 references), and help and docs pages are linked in bursts like news.
   - **Changed:** references are found by the address's shape, i.e. a `help.`, `support.`, `docs.` or `developer.` host, or a `/docs`, `/help` or `/support` path. That is a shape rule, not a site list. It finds all 10 seen.
   - **Changed:** government sites are not references (they publish dated press releases); they stay suggestions.
5. **Followed sites suggested again:** 5 on the server and 6 on the lab, all coming in through where stories start.
   - When no section qualifies, the code suggests the whole followed host. Instead, it goes to "missing from a source you follow".
   - **Bug:** an aggregator's most common post host counts as a site you follow (`SourceFacts.followed()`: a link aggregator's posts make a large tech company's site "followed"). That hides the site from link-based suggestions and labels its section "of a site you follow".
   - Fix: a source that isn't the publisher of its posts' addresses (`NOT_PUBLISHERS`, aggregators and Saved) follows no site by them.
6. **Ranking:**
   - **Proposed:** score = 3·ln(1+origins) + 2·ln(1+classics) + 1.5·ln(1+opened) + ln(1+voices) + a recency bonus, after platforms, references and followed sites are removed.
   - The first 30 hold 7–8 X accounts.
   - Origins and classics carry it; recency is nearly flat and opens are sparse.
   - 7 of the server's first-page sites refuse plain readers, so the follow test's labels decide their place (they sink).

## Not in this issue
- Reading walled or JavaScript-only sites (0081).
- Mark X's "same voice" (0078 channels).
