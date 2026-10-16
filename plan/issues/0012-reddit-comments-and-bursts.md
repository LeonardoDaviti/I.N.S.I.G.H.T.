# 0012 — Reddit: comments that load, and posts that don't flood the top

Status: **ready-for-agent** (owner observations on the server, 2026-10-16). Needs a Reddit app from the owner for the comments half.

## Problem Statement
- **Comments never load.** "That did not work — HTTP 403 while fetching https://www.reddit.com/r/LocalLLaMA/comments/…json". Reddit answers 403 to every unauthenticated JSON request from the server, whatever the User-Agent (already measured 2026-08-14; that is why post ingestion moved to `.rss`). Comments still use `.json`. Reddit is the only platform with comments, so "no comment fetching works".
- **Reddit floods the top.** r/LocalLLaMA posts about every 10 minutes, but its feed holds 25 posts and it is fetched every ~4 hours. Each fetch drops a burst of ~25 posts in one go. Their dates are right, but they arrive together, push the "N new posts" pill, and in "By source" the subreddit's group jumps to the top after every fetch, above sources with newer posts I care about.

## Solution
- **Comments through a Reddit login.** Connections gets a "Reddit" entry: the owner creates a Reddit "script" app once and pastes its client id and secret. INSIGHT then asks Reddit for comments through its official API with an app token. Without it, the comments button says "Add a Reddit app in Connections to load comments" and links there, instead of failing.
- **Smaller bursts.** A busy subreddit is fetched at most every hour (the scheduler tick), not every ~4 h, so each fetch brings a few posts, not 25.
- **"By source" orders groups by their newest unread post**, not their newest post, and a group with nothing unread sorts last.

## User Stories
1. As the reader, I want Reddit comments to load on a Reddit post, so that I can read the discussion in INSIGHT.
2. As the owner, I want to add Reddit app credentials in Connections, so that comments work.
3. As the owner, I want the credentials stored encrypted like every other connection, so that they are safe.
4. As the reader without the credentials, I want a clear note with a link to Connections, so that I know how to fix it.
5. As the reader, I want a failed comments load to say why (expired or wrong credentials), so that I can act.
6. As the reader, I want comments loaded once to stay with the post, so that reopening is instant (as today).
7. As the reader, I want a busy subreddit fetched more often, so that its posts arrive a few at a time.
8. As the reader, I want "By source" groups ordered by newest unread, so that a subreddit I've read doesn't jump to the top.
9. As the reader, I want sources with nothing unread at the end in "By source", so that the top is what I haven't read.
10. As the owner, I want post ingestion to stay on `.rss`, so that it keeps working without credentials.

## Implementation Decisions
- **Credentials:** a `reddit` connection kind (client id + secret) in the existing encrypted Connections store; Reddit's entry stops saying "Not needed". Never logged or printed.
- **Comments client:** the Reddit kind's comment fetch gets an app-only OAuth token (client-credentials grant, `https://www.reddit.com/api/v1/access_token`), caches it until expiry, and reads `https://oauth.reddit.com/<permalink>?limit=80&depth=8&sort=top&raw_json=1`. Same parser for the response. Without credentials it raises the existing "unavailable" outcome with a reason the post page shows.
- **Cadence:** the existing backlog guard for high-volume feeds (the interval is capped when a feed's window fills between fetches) uses the scheduler tick as its floor for feeds whose window holds less than the expected posts between fetches. No new setting.
- **By-source order:** the reader's by-source query orders groups by `MAX(sort_key) FILTER (unread)` then `MAX(sort_key)`.

## Testing Decisions
- Reddit kind tests with the fake HTTP: token request then OAuth comments request; a cached token is reused; no credentials → unavailable with the Connections reason; 401 → reason "check the Reddit app in Connections". Prior art: kind tests with `FakeHttp`.
- Cadence unit test: a feed whose 25-post window covers 4 h gets an interval ≤ the tick.
- Reader repository test: a group with only read posts sorts after a group with an older unread post.

## Out of Scope
- Reddit archive via OAuth (archive still uses `.json`); user-login (password) OAuth.

## Further Notes
- Server evidence: r/LocalLLaMA `mean_gap_hours 0.17`, interval basis `backlog_guard`, ~4.3 h interval; feed of 600 newest items correctly dated.
