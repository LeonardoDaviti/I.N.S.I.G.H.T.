# 0265 — A maker's page reached through another source is credited to the maker

Status: **built** (v10.32). Cases: `inkling-2-mini-maker-credited`, `openai-terra-same-address`
(plan/research/lab/cases.json). Measured rows: plan/research/v1032/maker-credited-0265.md (gitignored).

## The bug (production 2026-11-21)

A post is stored once, at its address (posts.url is unique). When an aggregator (Hacker News) stores a maker's
announcement page before the maker's own page watch fetches it, the row is the aggregator's until that fetch hands
it over (0167, `repo_posts._own_page`): for the release in the case, 8.7 hours (HN stored it at 22:10, the page watch
took it back at 06:53). In between, Mark X's News line read "Hacker News · <HN's title> · <HN's time>": the maker,
who said it first, hidden. Older rows stored before 0167 (HN's copy at the address with a trailing slash, the
maker's at the bare one) stay HN's for good, and after a hand-over HN keeps a citation post of the page
(`#!/cited-by/<hn>`) that also reads as HN's own.

## The rule (utils/byline.py: `page_owner`, `site_owners`)

Who wrote a post is Byline's (0185): `author` the writer when the feed did not write it, `via` the feed that
carried it. A page is now one more such case: when the feed holding it doesn't own it (own_pages.owns: not a
website source on the page's site — Hacker News, a link blog, Saved) and an **enabled website source on the page's
site** does, that source is its `author`; the carrier stays `via` ("Example Labs News via Hacker News").

- Of several sources on one site, the one whose own address's first path segment is the page's
  (`anthropic.com/research/...` -> the /research source). With none of them under it, the site's only source;
  several and none under: nobody (a platform site's user pages: `models.example/<org>/<model>` is not the
  platform blog's).
- A platform post's address (a tweet, a Telegram or Reddit post, a video, arXiv) is never a site's page.
- Display only: the stored source, voices, stories and the 0167 hand-over are unchanged. The hand-over stays the
  one decision of whose row a page is; this names the maker in the time before it and on what it cannot move.

Read by Mark X's News lines (`news._posts`) and every view reading `byline.bylines` (tracks, perspectives, post
refs). The frontend names a source-author as every source is named (`sourceLabel`, never a raw feed URL).

## Measured (production GET /api/markx/news?all=1, 2026-11-21 16:05, 614 rows; each line's url from
GET /api/posts/item/<id>, sources from GET /api/sources; 2,791 of 3,221 lines resolved)

| | lines | rows |
|---|---|---|
| carrier shown while a followed website source owns the address (before) | 27 | 26 |
| credited to the maker (after) | 22 | 22 |
| left as the carrier (several sources on the site, the page under none) | 5 | — |

By carrier, after: Hacker News 11, Saved 6, Daring Fireball 5. The 5 left: 4 Saved model cards on a model-hosting
site followed by its blog and one org page, and one legal page of a lab followed by two sections.

Known limit: a site followed through one narrow source (an author's feed of a magazine) credits that source for
any page of the site a link blog carries.

## Tests

backend/insight_core/tests/test_maker_credited_0265.py (pure rule + a seeded world: News lines and `bylines`);
frontend/src/lib/byline.test.ts (the 0265 case).
