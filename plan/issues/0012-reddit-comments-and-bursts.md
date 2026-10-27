# 0012 — Reddit: comments that load, and posts that don't flood the top

Status: **bursts half built** 2026-10-16, not deployed; **comments half waits for the owner**: Reddit reportedly now requires approval for new API apps, so first confirm a "script" app can be created (owner observations on the server, 2026-10-16). The old `.json` comments fetch (route, job, scraper) was removed in issue 0029; stored comments still show. Removed, restore from git (before issue 0029) if needed.

## Problem Statement
- **Comments never load.** "That did not work — HTTP 403 while fetching https://www.reddit.com/r/LocalLLaMA/comments/…json". Reddit answers 403 to every unauthenticated JSON request from the server, whatever the User-Agent (already measured 2026-08-14; that is why post ingestion moved to `.rss`). Comments still use `.json`. Reddit is the only platform with comments, so "no comment fetching works".
- **Reddit floods the top.** r/LocalLLaMA posts about every 10 minutes, but its feed holds 25 posts and it is fetched every ~4 hours. Each fetch drops a burst of ~25 posts in one go. Their dates are right, but they arrive together, push the "N new posts" pill, and in "By source" the subreddit's group jumps to the top after every fetch, above sources with newer posts I care about.

## Solution
- **Smaller bursts (build now).** A busy feed is polled before its window is a quarter full, so a subreddit brings a few posts per fetch, not 25. An "hourly" source is really due every hour, not every second hour.
- **Comments through a Reddit app (after the owner confirms one can be created).** Connections gets a "Reddit" provider: the owner creates a Reddit "script" app once and pastes its client id and secret. INSIGHT then asks Reddit's official API for comments with an app token. Without the app, the comments button says "Add a Reddit app in Connections to load comments" and links there, instead of failing.
- **Not changed:** the "By source" group order. Under Unread (the default) groups already follow the newest unread post, and a subreddit that really has the newest unread post belongs on top. Ordering by what I care about is the future issue 0013.

## User Stories
1. As the reader, I want Reddit comments to load on a Reddit post, so that I can read the discussion in INSIGHT.
2. As the owner, I want to add Reddit app credentials in Connections, so that comments work.
3. As the owner, I want the credentials stored encrypted like every other connection, so that they are safe.
4. As the reader without the credentials, I want a clear note with a link to Connections, so that I know how to fix it.
5. As the reader, I want a failed comments load to say why (expired or wrong credentials), so that I can act.
6. As the reader, I want comments loaded once to stay with the post, so that reopening is instant (as today).
7. As the reader, I want a busy subreddit fetched more often (and an hourly source really fetched hourly), so that its posts arrive a few at a time.
8. As the owner, I want post ingestion to stay on `.rss`, so that it keeps working without credentials.

## Implementation Decisions
### Bursts (build now)
- **The backlog guard's cap.** Today the guard caps the interval at `mean_gap × max_posts_per_fetch`, with a floor of 1 h. For Reddit that is 0.17 h × 25 = 4.25 h, which leaves no margin. Decision: when the guard binds, the interval is `max(BACKLOG_GUARD_MIN, cap / 4)`, so the feed is polled before its window is a quarter full. r/LocalLLaMA goes to about 1.06 h. Don't plumb the configurable tick into the schedule module; that would be a new seam.
- **Due slack.** `last_success_at` is recorded after the fetch, but ticks are anchored to their start. So a 1 h source fetched 5 min into a tick misses the next tick and waits two hours. Decision: the due check allows `DUE_SLACK = 10 min`, meaning a source is due when `now >= due - DUE_SLACK`.

### Comments (after the owner's confirmation; don't build before)
- **Provider.** `ProviderSpec("reddit", …, (FieldSpec("client_id"), FieldSpec("client_secret")), testable=True)` in the credentials service. Its test performs the token grant. Credentials reach the comments call through `CredentialProvider` / `default_credentials()`, as Substack's do. They are never logged or printed.
- **Token.** The client-credentials grant at `https://www.reddit.com/api/v1/access_token` sends form-encoded data with Basic auth. `KindHttp` gains a form option for that, and `FakeHttp` records it. The token is cached in the reddit kind module, keyed by client id, until it expires.
- **Comments request.** `https://oauth.reddit.com/<permalink>?limit=80&depth=8&sort=top&raw_json=1`, with the same parser as today.
- **Errors.** HTTP errors arrive as `ValueError("HTTP 401 …")`, so a 401 is detected by its status prefix and reported as "check the Reddit app in Connections". Without credentials, the call raises `KindUnavailable` with that reason. `KindUnavailable` maps to 409 in the API's known errors. On any comments failure, the post page shows the reason and a link to Sources → Connections. No error-code protocol.
- **Docs.** The reddit module docstring, the credentials service docstring, and `design/docs/pages/post.md`.

## Testing Decisions
- **Bursts.** Schedule unit tests:
  - a feed whose 25-post window covers 4.25 h gets about 1.06 h;
  - the 1 h floor holds;
  - a source with a 1 h interval, fetched 5 min into a tick, is due at the next tick.

  Prior art: the schedule tests.
- **Comments.** Reddit kind tests with `FakeHttp`:
  - a token request, then the OAuth comments request;
  - a cached token is reused;
  - no credentials gives `KindUnavailable` with the Connections reason;
  - a 401 gives the "check the Reddit app" reason.

  A route test that `KindUnavailable` becomes a 409.

## Out of Scope
- Reddit archive via OAuth (archive still uses `.json`); user-login (password) OAuth.

## Further Notes
- Server evidence: r/LocalLLaMA `mean_gap_hours 0.17`, interval basis `backlog_guard`, ~4.3 h interval; feed of 600 newest items correctly dated.
- As built: the guard binds when the interval exceeds a quarter of the window (`cap = mean_gap × posts / 4`, then `base > cap`), so every fast feed, not only one past its whole window, is polled at a quarter full. On the local preview that moves 4 fast RSS sources (gaps 2.6–3.4 h) from 24 h to 13–17 h.
