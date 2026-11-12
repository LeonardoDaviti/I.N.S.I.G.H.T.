# 0167 — A page's own source takes its row back, following a feed fetches its archive, paywalls named right

Status: **built** (2026-11-12) on branch `v1015-own-pages` (from main 7b651e5), not merged, not pushed. INSIGHT v10.15,
part A. Mark IX (ingestion, the post writer, sources). From experiment E5 (2026-11-12, rows in plan/research,
private): a company's own channel was missing from 53–65% of its events; part of that is INSIGHT's own doing.

**Constraints:** fix the class, never a site; keep everything (no post or derived row deleted; Mark IX/X rows on a
post stay valid); every fetch through the existing machinery (gates, budgets, the archive queue); tests stub every
request; no migration was needed.

## 1. A page's own source takes its row back from an aggregator

**Why.** A post is stored once, at its address (`posts.url` is unique), and `ON CONFLICT (url)` never changed its
source. So when an aggregator (a news aggregator's feed, a link blog, a trending list) stored a company's page first,
the company's own followed source (its feed, its page watch) fetched the same address later and only *updated* that
row: the row stayed the aggregator's, its text flipping between the two fetches. E5: a newsroom followed on day N
missed its own pages linked before; a research page watch's page held by an aggregator; 4 events blocked so.

**The rule** (`utils/own_pages.py`, one for the live save and the repair):
- **A source owns a page** when it is a website source (a feed, a page watch, a Substack: `source_kind` "site";
  never a platform account, the aggregator kind or Saved) whose own address is at the page's publication
  (`page_site`: the host without `www.`, and without a `blog.`/`news.`/`newsroom.` label; two writers' subdomains
  of one platform are two). The live save adds the strongest evidence: the source's own fetch brought the address.
- **The owner takes the row back** from a holder that doesn't own it (`PostsRepository._own_page`, before the
  insert, after 0122's `_saved_copy`): **the same row, its id kept**, moves to the owner (`hand_over`) and takes the
  owner's text. `metadata.taken_from` {source_id, at, citation} records it, kept by every later update.
- **The holder keeps a post of its own citing the page**: a new row at the page's address with
  `#!/cited-by/<holder id>` (a fragment `normalize_url` keeps, so it is an address of its own; a browser opening it
  opens the page), with the held row's title, text, dates and read state as they were, and `metadata.cites`
  {url, normalized_url, post_id}. Its page is never read again (full text and 0062's retries skip `cites`).
- **The aggregator's later fetches** of a page its owner holds go to its citation (`_as_citation`): they update the
  citation, never the owner's row. An aggregator that stores a page its owner already holds gets a citation at once.
- **Unchanged:** two sources that both own a page (a blog's feed and a page watch of one section) keep it where it
  is; a platform's post address (a tweet, a Telegram or Reddit post) never moves (one post, its reposts by, 0066);
  a Saved page is 0122's; a row of a source that doesn't own the page, fetched by another that doesn't either, is
  as before.

**Why one row moving, not a pair.** Every Mark IX and Mark X row about the page is keyed by the post id: its story
membership, readings, entity mentions, labels, News rows, notes, reader state. The page *is* that post; what
changes is whose post it is. Moving the id keeps all of them valid with no rewrite; the source change re-queues the
post for the story job (the `posts_story_queue_update` trigger) and Mark X reads sources at run time. The
aggregator's own voice is kept by its citation (a new post: it joins the page's story as a citation, as any post
linking it).

**The repair** (`scripts/repair_own_pages_0167.py`, dry run by default, resumable): the pages held by a source that
doesn't own them, at the publication of an enabled website source. A page moves when its owner's listing names it:
by default the listing is asked (a page watch's listing page and section sitemap; a feed's items and its site's post
sitemap), one source at a time, 2 s between requests; `--no-fetch` uses the stored evidence only (the owner's page
watch wrote the row, or 0084 B's rule names it). `--apply` moves (`hand_over`, as the live save does); `--state FILE`
records the owners done; a page moved is no candidate again.

Measured on the server's 5 Nov copy (a migrated scratch clone, `--no-fetch`): **8 pages would move** (a research
page watch's page from the aggregator; two news pages from a link blog; four of an AI lab's pages from the
aggregator and the link blog; one magazine page), **5 unsure** (left). Before the publication rule, the registrable
site (`site_of`) made a code host's 65 trending pages and 7 newsletter writers' pages candidates of unrelated
sources: a newsletter platform and a code host are one registrable site for many writers.

## 2. Following a feed fetches its archive; backdated items reach their stories

**Why.** A feed lists its newest items only (a blog's 20): a blog followed today held none of its older posts, so an
event of three months ago missed its own announcement.

**What it does** (`services/follow_archive.py`):
- `POST /api/sources` queues the new source's archive at once (`ArchiveJobs.enqueue`, the queue the ingestion process
  runs in turn, one per lane, inside the host gates and learned budgets), back to **the horizon**: the owner's
  reading window when it is a number of days, else **180 days** (`FOLLOW_ARCHIVE_DAYS`; the window at "every post",
  or never set). The answer says so: `archive` {queued, until, status, job_id} or {queued: false, reason}.
- **Which sources:** a website's own feed (`own_pages.owns`: never an aggregator's, whose archive would be months of
  other sites' pages) of a kind whose archive goes newest first and stops at a date (0130 C): a feed and a
  Substack publication. Its machinery is the archiver's as it is (0107 waits, 0108 moved blogs and sitemaps, 0143's
  ladder). Not: X and Telegram (the owner: no X archive now), a page watch (its pages aren't listed newest first, so
  its archive can't stop at a date: the source sheet's Archive, as before), a disabled source, one the archive
  refuses.
- **Existing sources, on demand:** `scripts/archive_on_follow_0167.py` (dry run by default; `--apply` queues;
  `--source <id>` one source whatever it holds) lists the enabled feeds with no archive ever and nothing older than
  the horizon. The source sheet's Archive (with its "back to a date") stays as it is. On the server's 5 Nov copy
  (dry run) it lists 4 feeds (a newsletter, a research group's feed, a company blog, a personal blog); 11 enabled
  sources are left by kind (X, Telegram, a page watch, YouTube, Saved) or because their feed holds no more.

**Backdated items and their stories.** The four E5 cases (an own page stored by an archive weeks after its story)
were read back from the server (GET only) and their causes are not the candidate finder's:
- an archive's posts never surface (`save_batch(live=False)`), so Mark X's time of the page is its own date;
- the candidate finder reads any post by its date when its vector arrives, its Mark IX story read then
  (`test_backdated_candidates_0167`: a page stored 40 days late pairs with its story's posts, not with the day it
  arrived);
- of the four, two pages are in a Mark X story now (one with the page as its first post), one made its own Mark X
  story with an early repost while the story E5 named began 3 days and 7 hours later (outside the 72-hour post
  window), and one was never joined (no specific subject; its join, if asked, not taken).
- What is left is the decision run's: an older Mark X story not merged into the one holding the own page, and a
  join not taken. That is `markx/decide.py` (another slice's area): **not changed here**; reported with the rows.

## 3. Paywalls named right

**Why.** A page read that met a paywall said "its page held nothing longer" (a newsletter on its own domain read as
plain RSS: its paid post's page held the teaser only).

**What it does:**
- `ingestion/kinds/paywall.py`: a page that says it is for paying readers, by its own standard markers, never a
  site's name: schema.org `isAccessibleForFree` false (JSON-LD, its string forms, or microdata); Open Graph
  `article:content_tier` "locked" (metered is readable); Substack's `_preloads` naming **the post's own** audience
  only_paid / founding / only_subscribers (a paid post the page recommends is no paywall).
- `full_text.read_page`: such a page ends **PAYWALLED** (`page_read_outcome`), `metadata.paywalled` true; its free
  part is taken only when longer than the feed's. A watched page (page watch, a saved page: `article_post`) is marked
  too. `teaser_reason` says **"for paid subscribers"** for any paywalled post (the Substack kind's teasers too).
- `FULL_TEXT_RULE` 2 → 3: the start's repair (0140) reads the posts left short (nothing longer, not the same article,
  a script needed) **once more**, so the stored ones are named right. Not measured on the server (its copy predates
  0140's outcomes): the count is `SELECT count(*) FROM posts WHERE metadata->'page_read_outcome'->>'outcome' IN
  ('nothing_longer','not_same_article','needs_script')`. `INSIGHT_FULL_TEXT_REPAIR=0` holds it.

**A Substack publication on its own domain is read as one** (`settings.substack`, which `SubstackKind.matches`
already takes): `substack.recognise` — the feed's or page's generator names Substack; or it carries substackcdn.com
assets **and** its `/api/v1/archive` answers as Substack's (asked only on that sign: a site with no sign costs no
request). Recognised:
- **at add** (`POST /api/sources`, an rss source that isn't a page watch: one request, the feed), the answer saying
  `recognised: "substack"`;
- **on every live fetch** of a generic feed whose generator is Substack (no request: the feed in hand;
  `FetchedPosts.recognised`, merged by the runner through `DbInspectionRefresher.recognised`): an existing source
  is read by the Substack kind from its next fetch;
- **in the source doctor** (a failing feed), before it looks for a replacement; the finding says so.
The owner pays for none of these publications now: their paid posts are stored as their teaser, marked paywalled,
"for paid subscribers". The cookie path is unchanged.

## Done when (tests, every request stubbed)
- `test_own_pages_0167` (8): the rule (owners, aggregators, link blogs, Saved, platforms, two writers of one host,
  a site's blog); the owner's fetch takes the row back, its id, story row, note and read state kept, the holder's
  citation with its text and read state; the owner's later fetch keeps the mark; the holder's later fetch updates its
  citation; an aggregator fetching an owned page gets a citation; two sources of one site keep it; the repair's dry
  run changes nothing, `--apply` moves what the listing names, a second run finds nothing.
- `test_paywalls_and_follow_0167` (16): the markers (and a recommended paid post being none); a paywalled page read,
  with nothing longer and with a longer free part; the Substack kind's teaser line; a watched page marked;
  recognition by generator (one request), by assets + API, none without a sign (no API request), none for Substack's
  own hosts; a live fetch recognising it and the runner's merge; the doctor recognising it; following a feed queues
  its archive to the horizon; a disabled source, a page watch and an aggregator's feed don't; the horizon by the reading window or 180
  days; the script on demand.
- `test_backdated_candidates_0167` (1): a page stored 40 days after its date pairs with its story's posts by its date.

## Left off
- The decision-run causes of part 2's four cases (stories not merged, a join not taken): `markx/decide.py`.
- A page watch's follow archive (its archive can't stop at a date): the button, as before.
- "Followed but outside the followed section" and "a second section" (E5): Discover's.
- The repair's listing reads go straight through `KindHttp` (2 s apart, one source at a time), not the host gates.
