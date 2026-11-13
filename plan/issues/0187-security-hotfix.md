# 0187 — Security hotfix v10.16.2: outgoing requests, stored HTML, size caps, expensive routes

Status: built on branch `v10162-security` (not merged, not deployed).

A static audit of v10.16.1 (2026-11-13) found eleven problems. The owner's decision for this release: fix what
needs no new step in his deploy and adds no friction to reading; the login, the CSRF/host checks and the
container hardening are their own issues (0192, 0193, 0194). Every fix below is a class with one mechanism,
in the module that owns the decision.

## In this hotfix

### C2 — outgoing requests could reach the server's own network (SSRF)

**Found.** `KindHttp` (ingestion/http.py), the client of every source kind, the feed finder, page-watch preview,
saved pages, source add, research seeds and Discover's reads, fetched any http(s) address, followed redirects
(urllib's default: up to 10, to any host) and never looked where the host resolved. A pasted
`http://postgres:5432/`, `http://backend:8000/api/...` (the API itself, from inside the network), a cloud metadata
address (169.254.169.254) or any LAN host was fetched, and a public page could redirect to one. The media proxy had
its own guard (resolve, refuse non-public, re-check each redirect), but it resolved once to check and urllib
resolved again to connect (DNS rebinding), and it was a second copy of the rule. TLS verification was skipped
for every `*.local` host.

**Built.** `AddressGuard` in ingestion/http.py is the one place:
- it resolves the host once, refuses it unless every address is global (private incl. Docker's 172.16/12,
  loopback, link-local incl. 169.254.169.254, CGNAT/Tailscale 100.64/10, unspecified, reserved, multicast; an
  IPv4-mapped IPv6 address judged as its IPv4 one), and connects to an address it checked: no second DNS answer;
- the exceptions are the bridges (`bridge_hosts()`): telegram.local, nitter.local, and every host in
  NITTER_HOSTS, TELEGRAM_RSS_HOSTS, INSIGHT_MEDIA_PRIVATE_HOSTS, RSS_SKIP_TLS_VERIFY_HOSTS (127.0.0.1 is not one
  by default: inside a container it is the container);
- its opener has only the http and https handlers, no environment proxy (a proxy would connect for us,
  unchecked), and a redirect handler: at most 3 redirects, http/https only, each hop's host checked as it
  connects, and a `Cookie` or `Authorization` header dropped when the host changes;
- TLS is unverified only for a bridge that resolves to a LAN address (its self-signed certificate) and the hosts
  RSS_SKIP_TLS_VERIFY_HOSTS names; a `.local` host that is not a bridge is verified.
- `KindHttp(guard=...)` uses it for every request; `MediaProxyService` opens through the same guard's opener
  (its private copy deleted; `AddressNotAllowed` is its 404, as before).

**Owner's deploy.** Nothing to set when the bridges are telegram.local / nitter.local or listed in NITTER_HOSTS /
TELEGRAM_RSS_HOSTS. Another LAN host read as a source (an RSSHub, a FreshRSS) needs its host in
INSIGHT_MEDIA_PRIVATE_HOSTS; until then its fetches fail with "<host> is not a public host".

### M1 — unbounded bodies (gzip bombs)

**Found.** `get_text`, `get_conditional` (no max_bytes) and `post_json` read the whole body, and `_unpacked`
decompressed it without a limit: a 10 KB gzip of zeros became gigabytes in memory. An error answer's body was
read whole too.

**Built.** `MAX_BODY_BYTES` = 10 MB, raw and unpacked, for every read of a whole body (`read_capped`): past it,
`BodyTooLarge` (an HttpError: that fetch fails, nothing else). A caller that needs more passes a larger
`max_bytes` to `get_text`, with its reason; a smaller one is never a way around the default (`body_cap`). An
error answer's body is read to 64 KB (200 characters are kept). `get_start` and `get_conditional(max_bytes=)`
keep their short reads.

### H1 — stored XSS on the post page

**Found.** `PostDetailPage.postPlainText` (Copy text) set a post's `content_html`, the feed's HTML, as a
detached div's `innerHTML` to read its text: the page's document loads its images, so `<img onerror=...>` ran in
INSIGHT's origin. The rendering itself is sanitized (rehype-sanitize); this side path was not.

**Built.** `lib/inertHtml.ts`: `htmlText` reads text from a DOMParser document (no window: nothing runs or
loads), `decodeEntities` decodes in a textarea of such a document. Both former uses (the post page, the Markdown
renderer's entity decoding) go through it. The app has no `dangerouslySetInnerHTML`, and its only `innerHTML` is
inertHtml's own, on a windowless document.

**CSP.** nginx sends `Content-Security-Policy`: `default-src 'self'`; `script-src 'self'` plus the hash of
index.html's theme script (lib/csp.test.ts fails when the script changes and the hash doesn't);
`style-src 'self' 'unsafe-inline'` (the app's libraries add <style> elements); images and media from `'self'`,
data:, blob: and any http(s) address (posts load through /api/media; a few images load raw); `connect-src 'self'`;
`object-src 'none'`; `base-uri 'self'`; `form-action 'self'`; `frame-ancestors 'self'`.
A build with `VITE_API_URL` pointing at another origin would need that origin in `connect-src` (DEPLOYMENT.md
says to leave it empty).

### M2 — expensive routes

**Built.**
- A fetch's `limit` (Fetch now, a track's fetch) is a whole number from 1 to `MAX_FETCH_LIMIT` = 500, checked by
  `FetchRequest` itself (400 otherwise); an archive is the way to read more.
- A search's offset cursor is at most `MAX_SEARCH_OFFSET` = 10,000 (`SearchQuery`; 400), Discover's suggestion
  offset too (422).
- One export at a time across both API processes: the export's connection holds a session advisory lock while it
  streams; a second one is `ExportBusy` (400, "Another export is running") before any byte.
- `run_rate`: at most 30 run starts a minute per API process (fetch now, run cycle, a track's fetch, archive
  run/queue/linked/resume), then 429 with Retry-After. A bounded deque of 30 times: no memory grows.

### M4 — the Substack cookie

**Found.** `substack.sid` was sent to any source the Substack kind reads: `*.substack.com`, and custom domains
marked `settings.substack`, which `recognise()` sets from a feed's generator line or substackcdn assets (anything
a site can write). When the subscriptions answer could not be read (UNKNOWN) the cookie went to all of them, and
urllib carried it along any redirect, to any host.

**Built.** `SubstackKind._cookie_goes_to`: the cookie goes only to substack.com and `*.substack.com`, and to a
custom domain Substack's own subscriptions answer lists as a publication you pay for. A look-alike is read as
one you don't pay for (its paid posts stored as teasers). KindHttp drops the cookie on a redirect to another host.

### M3 (part) — builds

- `yt-dlp` is pinned (2026.10.26, the server image's version) instead of floating; bump it on purpose.
- frontend/Dockerfile: `npm ci` only (no `|| npm install` fallback that could install versions outside the lock).

## Moved to their own issues

- 0192 — authentication (C1, H2): no route has a login; token minting and every owner action are open to
  anyone who reaches the frontend's port.
- 0193 — CSRF and trusted hosts.
- 0194 — container hardening: non-root users, base-image digests.

## Not changed (looked at)

- `services/youtube_service.py` fetches subtitle URLs with urllib directly; they come from yt-dlp's answer for a
  YouTube video (Google's hosts), not from a user. Left as is.
- nginx's 24-hour image cache (`/api/media`) answers a cached image to anyone who asks the same URL; the images
  are the posts' public images. Revisit with 0192.

## Tests

Backend (run in the test image, the touched modules only): `test_address_guard` (every address class refused
before connecting, bridges, DNS rebinding: one answer, connected to it; a redirect to an internal address; a
redirect to file:; at most 3 redirects; the cookie on same-host vs cross-host redirects; no env proxy; gzip bomb
and raw body over the cap; a caller raising the cap; post_json capped; an error body read in part),
`test_media_proxy` (through the shared guard: private host refused without connecting, redirect to internal
refused, allowed redirect followed), `test_substack_kind` (the cookie never goes to a look-alike),
`test_route_caps_0187` (fetch limit, search depth, run rate, every run route guarded), `test_export` (one export
at a time), and the existing KindHttp/kind/feed-finder/conditional/search/ingestion-route tests on the new seams.
Frontend: `lib/inertHtml.test.tsx` (no handler runs, the page's document untouched, parsed in a windowless
document), `lib/csp.test.ts` (the inline script's hash is in the policy), the post page and renderer tests.
