# 0023 — A GitHub feed in INSIGHT, without scrolling github.com

Status: **in progress** (owner, 2026-10-27): **Trending first**, added from an Add source template. Following later, if at all; releases are issue 0024.

## The owner's observation
"I like the GitHub feed, I found so many new things on it, but I don't want to scroll GitHub for that, so we need to build the GitHub feed ourselves."

## What GitHub offers (checked 2026-10-27)
| Part of github.com's home | Way in | Notes |
|---|---|---|
| **Following**: what people I follow star, create, fork, release | REST `GET /users/<me>/received_events` (works without a token for public events; 200 checked) | 60 requests an hour without a token, 5,000 with one; events of the last 90 days, at most 300 |
| **Trending** repositories (today / this week) | the `github.com/trending` page (200 checked); no official API | an HTML page, so it can change |
| **New popular repos** | REST search (`created:>date stars:>N`) | rate-limited without a token (403 seen) |
| **Releases** of repos I care about | `https://github.com/<owner>/<repo>/releases.atom` | plain Atom: works as an RSS source today |
| **"For you"** (GitHub's own recommendations) | none | not reachable outside github.com |
| My user's Atom feed (`github.com/<user>.atom`) | — | answered 502 when checked |

## Likely shape (to confirm)
- A `github` source kind for **Following**: the events grouped by repository, so "facebook/xyz — starred by 3 people you follow" is one post, not three. The post is the repository: its description and README as the body, its stars and language in the details, linked to github.com.
- **Trending** as a second mode of the same kind, or later.
- Releases need nothing new: add `releases.atom` feeds as RSS sources.
- A GitHub token in Connections is optional; it raises the limit and includes private events.

## Questions to decide
1. Which parts matter: Following, Trending, or both?
2. The owner's GitHub username (the Following feed is theirs).
3. A token in Connections now, or start without one?
