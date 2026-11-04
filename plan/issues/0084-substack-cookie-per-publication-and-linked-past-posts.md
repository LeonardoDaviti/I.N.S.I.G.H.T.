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

### Built (A)
Branch `issue-0084-substack-cookie` (2026-11-04), on main 20d18d5. Not merged, not deployed. No migration.
- **`ingestion/kinds/substack.py`**: each source is read in one of four ways, decided once per fetch from the subscriptions answer:
  - *you pay for it*: as before (cookie sent; a truncated `only_paid` post, or a 401/403, is "expired");
  - *you don't* (free, not subscribed, or no cookie at all): no cookie on the archive or post requests, a paid post is stored as its teaser with `metadata.paywalled = true`, never an error;
  - *the subscriptions API answered 401/403*: no cookie; a publication with a truncated `only_paid` post is unavailable ("expired"), free ones are read (Decided 4, "paid publication" read as one that has paid posts: with a rejected cookie we can't know which ones you paid for);
  - *the answer can't be read* (another error, an unexpected shape, an empty list, or no entry recognised as paid): the cookie is sent everywhere as before, but a teaser is stored, never an error. This keeps full text on the publication you pay for if Substack's shape isn't the one assumed, and never puts a source in error. Its cost: in that case an expired cookie is not detected.
- **Asked once per run**: the answer is kept in memory on the kind for `SUBSCRIPTIONS_TTL_S` (600 s), keyed by a hash of the cookie (a new cookie asks again). An unreadable answer is not kept. The cookie is never logged or put in a message.
- **The shape assumed** (not verified, no request made from this machine; `paid_publication_hosts`): a JSON object whose `subscriptions` is a list. An entry is paid when `membership_state` (or `type`, `subscription_type`, `plan`) is one of `subscribed`, `paid`, `founding`, `comp`, `gift`, or when a flag `paid` / `is_paid` / `isPaid` / `is_paid_subscriber` / `is_founding` is `true`. Anything missing means not paid (`free_signup` is not paid). The entry's publication is embedded (`publication: {subdomain, custom_domain, base_url}`) or found by `publication_id` in a top-level `publications` list (`id`, `subdomain`, `custom_domain`). Hosts are matched without `www.`: `<subdomain>.substack.com` and the custom domain. **To check on the server:** the connection test's count. If it says "no publication you pay for found" while you pay for one, the shape is not the one assumed: fetches still work (the unreadable case), but expiry isn't detected.
- **The connection test** (`check_session`): "Signed in · full text on N publication(s) you pay for". With a source you pay for, it also reads its newest paid post ("· “title” reads in full"; a teaser is "expired"). "Signed in · no publication you pay for found" when none is recognised. A 401/403 is "expired"; a failed request is "Could not check the Substack session: …".
- **Source health** (Decided 6): the schedule view (`repo_fetch_state.load_schedule_view`) gains `paid_preview`, the `metadata.paywalled` of the source's newest `only_paid` post. `operations_service` adds the kind's `reading_notice(source)` to the row's `reading_notice`, which source settings already show: "Paid posts: preview only (no subscription)" when a cookie is set and that post is a teaser. Without a cookie the existing notice ("Add your Substack session…") stays.
- **The repair** (Decided 7): nothing stored changes. On the next fetch the 4 sources read without the cookie and succeed, which clears their error.
- **Tests**: backend 1357 pass (`./run-tests.sh`). New: paid-subscribed (full, cookie sent; a teaser means expired), free-subscribed and not subscribed (no cookie, teaser, no error), a custom domain you pay for, 401 on the subscriptions API (the paid publication expired, a free one read without the cookie), an unreadable answer (cookie sent, teaser, no error), one subscriptions request per run, the parser's defensive reads, the check's messages, the health note, and `paid_preview` against the database. Fixtures use `example.substack.com`; the real name the two test files used is gone.
- **The real-data check** (`insight_lab`, clock 2026-10-30 21:31): **PASS**. Cases: none changes state. Invariants: all equal to main's. Diff: 0 in every part (titles, text starts, link titles, roundups, story membership, origins, News, Classics, Discover).

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
