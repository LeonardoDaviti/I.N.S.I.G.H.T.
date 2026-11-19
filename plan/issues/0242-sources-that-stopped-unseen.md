# 0242 — v10.26 slice E: sources that stopped without anyone seeing

Backlog item #6 of 0237. No migration (0169 not used: every state fits the existing columns, see below).

## 1. The collision guard stopped whole feeds
**Wrong.** `kinds/base.collapsed` (0137 A1) failed a fetch whenever any two distinct items shared one address. A blog
feed of 48 items, 2 of which share one address, was a failed fetch every run; the source backed off, went dormant and
has had nothing since 11-13. The guard was meant for feeds that collapse (888 items on 2 addresses).
**Changed.** `collapsed` fails only when the feed collapses: over `COLLAPSED_SHARE` (half) of its distinct items fold
into another item's address. The two server cases set the line: the blog loses 1 of 48 (2%), the collapsed feed 886 of
888 (99.8%); half is the middle of the gap and reads as "most items share a few addresses". Not tuned beyond that. A
feed under the line is stored as the posts it is distinct as (the address upsert keeps one per address) and the fetch
carries a warning, `shared_addresses`: "2 of 48 items share 1 address: 47 posts stored". `checked_fetch` joins it
with the skipped warning; `generic_rss.fetch_latest` now passes the warning on (it passed only the failure).

**The 888 → 2 class.** `parsing._identities` already used an item's guid when ≥ 3 items with other identities share
its link, but it compared links as raw strings. Links that differ only by what `normalize_url` drops (a fragment:
`/changelog#v1-2`, `/changelog#v1-3`; tracking parameters) were "not shared", each item kept its link, and the save
folded them into one post per page. Now an address is shared as posts are matched (normalized), whether it is the
item's link or its guid; a guid that is itself the shared page with a fragment (`guid=/changelog#v2-3`) is not the
item's address either, so the guid becomes the item's token on the feed's address (`ITEM_PARAM`, as for any shared
link). A guid address of its own (`/ep/3`) is still kept; two items sharing one link stay one post, as before.
I could not see the real 888-item feed (no real data); the fragment form is my reading of "its items all link one
page". If its items have no guid and no title-date, they still collapse and fail, which is right.

## 2. Reddit ended its feeds
**Wrong.** Server 2026-11-19: `/r/<sub>/new/.rss` answers 404 or 429, `.json` 403, old.reddit 403. Reddit ended
subreddit RSS on 2026-11-13 (reports) and is closing unregistered API access. The busiest source has delivered
nothing since 11-17, as backoff failures.
**Changed.** `kinds/reddit.py` reads through Reddit's OAuth API: application-only OAuth (`grant_type=client_credentials`,
HTTP Basic with the app's client id and secret, `www.reddit.com/api/v1/access_token`), then
`oauth.reddit.com/r/<sub>/new?limit=…&raw_json=1` with `Authorization: bearer …` and the User-Agent Reddit's rules ask,
`server:insight-reader:1.0 (by /u/<username>)`. The archive pages `/r/<sub>/top?t=all` by `after` through the same
client and listing reader (`listing_posts`); the archive is no longer refused once credentials are there. The token is
one string per process on the kind, asked again a minute before it expires or once on a 401. `KindHttp.post_form` is
the form POST (`post_json` and it share `_post_sync`); the old `reddit_user_agent` / `REDDIT_USER_AGENT` is gone.
- Credentials: provider `reddit` {client_id, client_secret, username} in Sources → Connections
  (`credentials_service.PROVIDERS`, checked by `normalise_value`, Test asks a token), read through
  `ingestion/credentials.py` like the other kinds.
- Without them: `REDDIT_PROFILE.requires = "reddit_creds"`; `schedule.availability_from_env` sets `reddit_reason`, so
  the source is `unavailable` with "Reddit closed its feeds: add Reddit credentials in Sources → Connections", never
  fetched, never backed off. Credentials Reddit refuses are `KindUnavailable` with "Reddit refused the app's
  credentials: …" (unavailable, not backoff).
- Any `/r/<sub>` address is this kind now, an old `…/.rss` feed added as a plain feed too (it can only 404); one
  thread's page (`/comments/`) and `/user/` feeds are not.
- DEPLOYMENT.md: the owner's steps to register a "script" app.

## 3. The flag in front of the owner
**Wrong.** "1 source failed" fired every run as an alert row; nobody saw it.
**Changed.** `operations_service.stalled_fields` (the health row's `stalled` {since, days, failures}; the summary's
`stalled`): a source that is on, whose last success (else the day it was added) is older than
max(`STALLED_FLOOR` 3 days, `STALLED_INTERVALS` 5 × its interval in force), or that failed `STALLED_FAILURES` 5 times
in a row. Unavailable sources count (the Reddit case). Computed from the row's own data, no query added.
- Sources page: a warning notice "N sources stopped" with Show them (the new `stalled` chip, "Stopped"); each row's
  fact says why first (`sourceList.stalledNote`: the unavailable reason, the dead host, or "nothing fetched for 6
  days, failed 9 times in a row").
- Reader's nav: "N sources stopped" under Main feed, linking `/settings/sources?status=stalled`, from the same cached
  health query the reader already loads; nothing when none.

## 4. Dead hosts
**Changed.** `HttpError.unreachable`: the host does not resolve (`AddressGuard.addresses`), refuses, or has no route
(`ECONNREFUSED`, `ENETUNREACH`, `EHOSTUNREACH`, `socket.gaierror`). `source_doctor.dead_finding`: an unreachable or
timing-out host whose source has not worked for `DEAD_AFTER` (14 days, since its last success, else since it was
added) is recorded `{dead, host, since, reason, note}` in the doctor's finding (any kind with an address; once a day;
not in a dismissed streak). The health row's `dead`; the source sheet says "gone.example does not resolve or has no
route: this source looks dead … Switch it off, or replace it with another address; INSIGHT never removes it." Nothing
is switched off or deleted. Under 14 days an unreachable host is an ordinary failure (looked at after 3), so a DNS
blip is no finding. A success clears it (the existing `record_success`).

## Stored state
None new. The token is process memory on the kind (one string). The dead mark lives in `source_fetch_state
.doctor_finding` like every doctor finding; `stalled` is derived per request.

## Tests
- `tests/test_ingestion_health_0242.py` (29): the collapse line (48 → 47 stored with a warning, 888 → 2 fails, the
  half line), fragment-shared links and guids, Reddit OAuth on a recorded-shape listing (`tests/fixtures/reddit/
  new_listing.json`, invented data): no credentials, token and headers, reuse and expiry, 401 refresh, refused
  credentials, archive paging, which addresses match, the Connection values; the stalled rule; dead hosts (the
  HTTP client's flags, 14 days, dismissed, once a day, bare handles, health fields).
- Updated: `test_source_health` (summary has `stalled`), `test_source_kinds` (Reddit reads OAuth; `.rss` subreddit
  addresses are the reddit kind), `test_credentials` (Reddit is listed), `test_source_fetch_service` (Reddit archives
  refused only without credentials).
- Frontend: `stoppedSources.test.tsx` (the note, the chip, the dead notice, the nav link).

## Owed on real data (not measured: no real data allowed)
1. After the owner registers the app: one forced fetch of the Reddit source (`/api/sources/<id>/fetch`) — posts
   arrive, `external_id` matches the stored RSS ids (`SELECT count(*) FROM posts WHERE source_id=… AND external_id IN
   (…)` on the overlap), no duplicates by URL (RSS stored `https://www.reddit.com/r/…`; OAuth stores
   `https://reddit.com/r/…`; both normalize to one address — check one known post).
2. The two collapsed feeds: re-run each fetch on a copy and record (items, distinct addresses, stored, failure,
   warning). Expected: the 48-item blog stores 47 with a warning and stops failing; the 888-item feed stores 888 if
   its links differ by fragment or its guids are distinct, else still fails. Report the real shape of its items.
3. How many enabled sources the stalled rule flags on the server (`GET /api/sources/health` → `summary.stalled`), and
   each one's reason; the expected six from the 0237 note plus Reddit. A flag on a source that works is a wrong rule.
4. The two dead hosts: after one fetch each, their `doctor_finding.dead` and `reason`.

## Risks
- Reddit's app registration may now need Reddit's approval (its developer terms / access requests); I could not try it.
  The token endpoint, the OAuth host and the listing shape are Reddit's documented API, not tested against Reddit.
- Changing the shared-address rule can move the address of items whose links differed only by a fragment and that
  were stored at the link before: on their next fetch they are stored at `?insight_item=<guid>`, a new post beside
  the old one. That is the 888 class itself (which stored 2 posts), so few posts, but measure it (owed 2).
