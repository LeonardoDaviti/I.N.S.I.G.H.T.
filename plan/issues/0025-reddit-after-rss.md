# 0025 — Reddit after its RSS ends (13 Nov 2026)

Status: **decided: no change** (owner, 2026-10-27): keep reading Reddit as today; when its feeds stop, they stop. Related: 0012 (Reddit comments).

## What Reddit announced (30 Sep 2026; TechCrunch, TechRepublic, r/redditdev, checked 2026-10-27)
- **31 Oct 2026:** new API access requests end.
- **13 Nov 2026:** RSS feeds stop, "no replacement" outside communities you moderate.
- **12 Jan 2027:** API access removed for apps that have not registered.
- **March 2027:** the remaining public API ends, registered apps included (except commercial data deals).

INSIGHT reads every subreddit from `/r/<sub>/new/.rss` (`ingestion/kinds/reddit.py`). Unauthenticated `.json` already answers 403 from the server (measured 2026-08-14), so the "JSON listing" is no replacement.

## Options
1. **End Reddit gracefully (S).** From 13 Nov, Reddit sources say "Reddit ended its feeds on 13 Nov 2026" instead of failing into backoff; stored posts stay readable; adding a Reddit source says so. No new API work.
2. **A registered app until March 2027 (S–M).** Request a Reddit "script" app **before 31 Oct 2026**, then fetch listings and comments over OAuth (0012's comments half). Works for about four months at most, if Reddit approves it.
3. **Third-party bridges** (RSSHub, Redlib…): they read the same Reddit and lose access the same way. Not recommended.

## Recommendation
Option 1 before 13 Nov. Option 2 only if Reddit matters enough for the next four months *and* the app request goes in before 31 Oct; it would carry 0012's comments too.
