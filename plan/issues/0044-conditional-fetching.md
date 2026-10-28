# 0044 — Conditional fetching: an unchanged feed costs nothing

Status: **built, not deployed** (2026-10-28; migration 0034). Planned for v9.5 (owner, 2026-10-28).

## Why
Every fetch downloads every feed in full, even when nothing changed. Most feeds change a few times a day at most. Servers that support it can answer **304 Not Modified**, with no body, when we send what they told us last time (`ETag` → `If-None-Match`, `Last-Modified` → `If-Modified-Since`). Page watching (0028) and change watching (0039) read pages the same way, so they gain from it too.

## Decided
- **The HTTP layer** (`ingestion/http.py`, `KindHttp`): a conditional GET that sends the stored validators and returns either "not modified" or the body with the new validators. Follow the existing style (`get_text`, `HttpError`). Redirects keep working, gzip and deflate unpacking (5563f00) still applies, and a 304 is never an error.
- **What is stored:** the validators per fetched address (the feed, a page-watch page, its sitemap), in the fetch state (`source_fetch_state`, or a small table if one source reads several addresses). Migration **0034**.
- **Which kinds use it:** every kind that reads one address per fetch, generic RSS and Atom first, then page watch (its page and its sitemap). Kinds with APIs or sessions (Telegram, Reddit, YouTube, X/Nitter, site adapters) stay as they are unless it's trivial.
- **What a 304 means downstream:** a successful fetch with 0 new posts. Health stays green, backoff is not touched, the source doctor (0036) is never woken, and the run's events say "unchanged" (shown the same calm way as any fetch with no new posts).
- **Safety:**
  - a server that answers 304 wrongly would hide new posts, so always fetch in full when the stored validators are older than a limit (e.g. 7 days), or when the owner presses "Fetch now" on one source;
  - a feed answering 200 with the same body still works as today.
- **Measured:** on the 32 big sites (`~/.cache/insight-checks/bigsites.py`, or a direct equivalent if it needs the preview API) and on the server's real feed list (`backend/insight_core/config/sources.json`, read only), record how many feeds send an ETag, a Last-Modified, both or neither, and how many answer 304 on a second request. Write the numbers into this issue.

## Done when
- Backend tests cover: a 304 path, a 200 with new validators, validators per address, the full-fetch fallback after the age limit, "Fetch now" forcing a full fetch, the doctor not woken, and gzip with a 304.
- The measured table is in this issue.

## Built
- **The HTTP layer** (`ingestion/http.py`), for any address, not only feeds (0039 builds on it):
  - `Validators(etag, last_modified, learned_at)`: the two headers verbatim; falsy when neither.
    `Validators.of(headers)` reads them from an answer, `request_headers()` gives
    `If-None-Match` / `If-Modified-Since`.
  - `await KindHttp.get_conditional(url, validators=None, *, max_bytes=None) -> Conditional`.
    `Conditional(body, url, headers, validators)`: `body` is None on a 304 (`not_modified`), else
    the body with gzip/deflate undone (`text` decodes it); `url` is where redirects landed (the
    validators go along); `max_bytes` reads the body the way `get_start` does (deadline overall).
    A 304 is never an error, even one naming `Content-Encoding: gzip`; every other failure is the
    usual `HttpError`. `get_start`'s reading loop is now `_read_start`, shared by both.
  - `AddressMemory(stored, *, now, full=False, max_age=VALIDATORS_MAX_AGE)`: one fetch's
    validators per address. `sending(url)` is what a GET sends (None when `full`, nothing is
    stored, or the stored ones are older than **7 days**); `await memory.get(http, url, max_bytes=)`
    asks and learns (a 200's validators dated now, a 304's keeping their date, so they still age);
    `learned` is what to keep, `forget()` keeps nothing, `unchanged` is every address asked
    answered 304, `changed` is learned differs from stored.
- **Stored** in a small table, `source_fetch_validators (source_id, url, etag, last_modified,
  learned_at)`, one row per address a source reads (migration 0034, cascades with the source).
  `FetchStateRepository.load_validators / replace_validators`, `DbFetchStateStore.load_validators /
  save_validators` (a source's rows are replaced whole).
- **Kinds:** `BaseKind.conditional` (False) marks a kind whose `fetch_latest` takes `memory=`.
  - `generic_rss`: the feed through the memory; a 304 is no posts (no article page is read).
  - `page_watch`: `discover_changed` asks the listing page, then each sitemap file the last fetch
    read; all 304 is no posts. The first that answers in full (or a sitemap that fails) ends the
    asking and the discovery runs in full, using that answer rather than asking twice.
    robots.txt is read as before. Validators are kept only when every address read gave some and
    the fetch left no candidate unread (a limit or SKIP_READS cut it short), so its backlog is
    still read on the next fetch.
  - Telegram, Reddit, YouTube, Substack, Nitter and the site adapters are unchanged; previews,
    inspections and archives read in full.
- **Runner:** loads the due conditional sources' validators once per run, builds an
  `AddressMemory` per fetch (fresh for the retry after a limiting host), and keeps what it learned
  only when the outcome is a success and the save worked; when any post of the source failed to
  save it keeps nothing, so the next fetch reads in full. **"Fetch now" on one source**
  (`SourceSelector.source`) reads every address in full. A 304 is `empty` like any fetch with no
  new posts: health green, failures and backoff reset as on any success, the source doctor (which
  only wakes on `error`) never sees it. The `source` event carries `unchanged: true` and the job
  line reads "Simon Willison: unchanged · 3 of 81 sources" (info level, no frontend change).
- **Limits:** a server that ignores the validators still answers 200 and works as today. Apache's
  `-gzip` ETags (mod_deflate) never match, so those feeds answer 200 (2 below); sending the bare
  ETag too would fix that and is not done. The measurement covers each feed and each followed
  page, not page-watch sitemap files.
- Tests: `backend/insight_core/tests/test_conditional_fetching.py` (28: a real local server for
  200 + validators, 304, either validator alone, a redirect, gzip with a 304, the byte cap and a
  404; the memory's dates, age limit, full and forget; generic RSS and page watch unchanged /
  changed / backlog / an address without validators; the runner: validators per address after the
  save, an unchanged feed calm and the doctor not woken, the "unchanged" line, the age-limit
  fallback, Fetch now, a failed save; the table per source and address). Backend suite: 812 OK.

## Measured (2026-10-28, from this machine, 2 GETs per address 3 s apart, the second only when the first gave validators)
The server's feed list: the 188 rss entries of `sources.json` less the 45 Telegram and Nitter
bridge addresses (`telegram.local`, `nitter.local`; their kinds are not conditional) = 143 web
feeds. The 32 big sites: the address each is fetched from per `big41-branch.json` (the feed the
finder found, else the page followed), 31 addresses (cursor.com's blog and changelog share one
feed).

| | sources.json feeds | big sites: feeds | big sites: pages | big sites: all |
|---|---|---|---|---|
| Addresses | 143 | 15 | 16 | 31 |
| Answered | 139 | 15 | 12 | 27 |
| ETag and Last-Modified | 62 | 6 | 1 | 7 |
| ETag only | 48 | 2 | 5 | 7 |
| Last-Modified only | 14 | 3 | 0 | 3 |
| Neither | 15 | 4 | 6 | 10 |
| **Answered 304 the second time** | **106 of 124** | **10 of 11** | **6 of 6** | **16 of 17** |
| 200 again, same body | 11 | 1 | 0 | 1 |
| 200 again, changed body and ETag | 6 | 0 | 0 | 0 |
| Second request failed | 1 (timeout) | 0 | 0 | 0 |

- **106 of the 139 feeds that answered (76%)** will cost one header-only answer when unchanged;
  on the big sites 16 of 27 (59%), and every followed page that sends validators.
- The 11 feeds that answered 200 with the same body ignore what was sent: 4 sent only
  Last-Modified (feeds.feedburner.com, oldvcr.blogspot.com, research.google/blog/rss, vas3k.blog;
  research.google is also the big sites' one 200), 2 are Apache `-gzip` ETags (aresluna.org,
  daringfireball.net), 5 ignore their own ETag (jyn.dev, mariozechner.at, matduggan.com,
  nvidianews.nvidia.com, downtowndougbrown.com). The 6 with a changed body carry per-request
  content under a new weak ETag (garymarcus, guzey and lcamtuf on substack.com, dwarkesh.com,
  oneusefulthing.org, timsh.org). All 17 work as today.
- Failed the first read (not about this issue): joanwestenberg.com/rss 404, rachelbythebay.com
  timeout, chiark.greenend.org.uk connection error, tedunangst.com DNS; big sites tesla.com,
  reuters.com, apnews.com, axios.com refuse us (401/403).

