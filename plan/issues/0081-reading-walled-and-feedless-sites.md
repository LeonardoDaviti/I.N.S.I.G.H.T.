# 0081 — Reading walled and feedless sites: more places to look, a real browser when needed, headlines when that's all there is

Status: **on hold** (owner, 2026-11-04: "we are not doing 0081 rn, skip it"). Drafted on the owner's question "we can't scrape everything? why? you can find solution for that". Not in the plan until the owner brings it back. Needs 0080's follow test to know which sites to try.

**Constraints:** download nothing until the owner says (a browser image is a large download); generalize, so no lists of sites; measure on the lab and on the server's sources; never break a paywall or a login.

## Why some sites can't be read today
From the 2026-11-04 test of Discover's top sites: 10 of 60 refuse plain readers with 401 or 403, 2 refuse with 400 or 406, and 18 home pages announce no feed. There are three kinds of wall:
1. **Bot walls:** the site answers a browser but refuses a script (Cloudflare and similar checks, or a missing browser fingerprint). Its feed often still works: a large lab whose pages answer 403 serves its news feed to us every day.
2. **No feed:** the page is plain or built by JavaScript, with no RSS or Atom. Page watching (0031, 0054) reads plain pages, not JavaScript-built ones.
3. **Paywalls and logins:** the text is for subscribers. Getting around that is not something INSIGHT does.

## Decided (proposed)
1. **More places to look, in this order, for every source add and repair** (the source-adding rule: the feed finder, then page watching):
   1. the page's announced feeds;
   2. the usual feed paths;
   3. the site's `sitemap.xml` and news sitemaps (they list every article with its date);
   4. page watching.

   Each answer is stored with the source's anatomy (0054), so health can say how the source is read.
2. **A real browser, only where it's needed:**
   - a separate container running headless Chromium, started only when a source's plain read fails twice the same way (401, 403, a bot check page, or a page whose text appears only after scripts run);
   - it reads like a person opening the page: one page at a time, the site's robots rules kept, at the source's own pace;
   - **learned per source from its failures, never from a list of sites;**
   - its memory and time per page are measured before adopting; it stops when idle (the 0072 memory lesson);
   - **decide:** the container image (Playwright's or a plain Chromium), its size, and whether the server can hold it.
3. **Headlines only, said plainly:**
   - for a site that a paywall or login stops, the source keeps what is public: the headline, the date, the opening the feed or sitemap gives, and the address;
   - each post says "Headlines only: open the original to read";
   - the source's health says why, so it is never shown as a broken source.
4. **A public archived copy as a fallback, for a page that has gone** (404 or 410), never for a paywalled one: the Internet Archive's copy, when one exists, linked as "archived copy".
5. **Backoff that fits the error (from a feed service failing with 502, 2026-11-03):**
   - a 5xx is the other server's trouble, so retry within hours, not days;
   - a 401 or 403 is a wall, so try the next way of reading (1 → 2 → 3), not the same request again;
   - a 404 or 410 means the source has moved, so repair it (the feed finder).
   - The health text names the site, not "the server": "example.org is failing (HTTP 502): its own server didn't answer, usually temporary."

## Measured before adopting
- How many of the server's sources, and of Discover's first 60, each way reads (1–4), and what each costs in time and memory.
- The browser's container size and memory, idle and per page.
- That nothing already read well changes (0075's diff).

## Not in this issue
- Logging in to sites for the owner (credentials exist for Telegram and others; a site login is a separate decision).
- Breaking paywalls: never.
