# 0084 — Substack: the cookie only where you pay; and a source's own older posts that its posts link

Status: **spec** (2026-11-04), from the owner's bug report: "it fetched kaitchup, but it does not fetch other substack feeds, because I have no subscription on them … also … some post might mention an older post that we don't have … can we parse it and store?" Part A is a bug fix (v9.16). Part B is a small feature (v9.16 or v9.17).

**Constraints:** download nothing beyond the feeds a fetch already reads; no real names in committed files or fixtures; nothing merges unless `scripts/realdata-check.sh` passes; the cookie is never logged or put in an error message.

## A. The cookie only where you pay (bug)
**Today** (the server, 2026-11-04):
- 4 of 12 Substack sources are in error, "Substack session expired — update it in Sources → Connections", although the cookie is fine.
- **The cause** is in `ingestion/kinds/substack.py`, `_to_post`: with a cookie set, any `only_paid` post that comes back truncated raises "expired". On a publication you don't pay for, a truncated paid post is normal, and it stops the whole source.

**Decided:**
1. **Which publications you pay for:**
   - asked once per fetch run of Substack's subscriptions API (`SUBSCRIPTIONS_URL`), kept in memory for the run;
   - it holds each publication you're subscribed to, with its paid or free state, read defensively (fields missing means "not paid").
2. **A publication you pay for:** as today. A truncated paid post means the session expired, so the source is unavailable until the cookie is updated.
3. **Any other publication** (free, or paid with no subscription):
   - the cookie isn't sent;
   - a paid post is stored as its public teaser, with `metadata.paywalled = true`, as without a cookie;
   - never an error.
4. **If the subscriptions API answers 401 or 403,** the session expired: every paid publication is unavailable, and free ones are read without the cookie.
5. **The connection test** (`check_session`) says which publications it reads in full: "Signed in · full text on 1 publication you pay for".
6. **A source's health** for a paywalled publication says "Paid posts: preview only (no subscription)", not an error.
7. **The repair:** on the first fetch after this, the 4 sources in error recover on their own; nothing to do by hand.

**Tests:** fixtures for paid-subscribed, free-subscribed, not subscribed, and an expired session (401 on the subscriptions API).

## B. A source's own older posts that its posts link
**Today:**
- A post that links an older post of the same publication, one we don't store, gets nothing. Neither the archive nor Discover fetches it.
- Discover's "missing from a source you follow" (0065) lists only pages that **start stories**.

Measured on the lab (posts linking `<publication>/p/…` of a followed Substack):

| | linked | not stored |
|---|---|---|
| all 7 Substack publications | 79 | 43 |
| the largest | 20 | 17 |

**The archive** reaches far back for Substack: the archive API pages back to the first post (one publication: about 540 posts, back to 2023). So most of these come in by running that source's archive. The rest are pages the archive doesn't list, or sources whose archive can't page.

**Decided:**
1. **"Linked, not stored"** is counted per followed source from what is stored: its own pages (its site, or its publication's path) that any stored post links, and that no stored post is.
2. **Fill them with the source's own reader, one page each:**
   - Substack's `read_post`, the full-text repair path every kind with `read_post` has;
   - the site reader for websites.

   Each is stored as a post of that source, with its real date.
   - Paced like the archive: one request per page delay.
   - Never more than the linked list.
   - Never for a page behind a paywall the source can't read (stored as its teaser, as A says).
3. **Where it shows:** the source's Archive section gets "Linked by your posts, not stored: 17 · Fetch them". A source whose archive can page offers the archive first ("Run the archive: it holds them").
4. **Done when:** on a lab copy, the linked-not-stored count of every Substack source after a fill is 0, except pages that answer 404 or 410 (listed); the real-data check passes (expect new posts and their stories, nothing else).

## Not in this issue
- Fetching any linked page of a site you don't follow (that's Discover).
- A paid subscription's login flow (the cookie stays pasted in Connections).
