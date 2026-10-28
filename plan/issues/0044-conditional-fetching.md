# 0044 — Conditional fetching: an unchanged feed costs nothing

Status: **planned** for v9.5 (owner, 2026-10-28).

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
