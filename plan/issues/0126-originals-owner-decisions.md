# 0126 — Collect originals, the owner's four decisions: gift links kept for clicking and ignored for matching, collected pages only inside their story, the quoted tweet's link, on by default

Status: **built** (branch `issue-0126-originals-owner-decisions`, 2026-11-07), the real-data check passes; not merged. Mark IX (addresses, the reader, the scheduler's settings). Numbered 0126: 0125 is taken by another session's spec (`0125-connected-earlier-later-outside.md`, uncommitted in the main checkout). Builds on 0109 B1 (the tracking keys, migration 0067: links stored with a tracker read again), 0113 (Discover Pages), 0114, 0122 (fetch the source before saving), 0123 (Collect originals, migration 0071).

**The owner (2026-11-07)**, answering 0123's three open questions and its default: "all your recommendations accepted".

**Constraints:**
- keep everything: no post or derived row is deleted (a link row whose address changes is rewritten by its post's links, as 0067 did);
- never fetch with a token: a page known only by a gift link is walled (0123), whatever its stored address says;
- no real names in committed files; fix the class, never a site;
- download nothing; tests stub every request;
- measured on the server's copy (`insight_server_1105`, read-only; scratch copies) before adopting;
- nothing merges unless `scripts/realdata-check.sh` passes.

## 1. Access tokens: kept for clicking, ignored for matching

**Today:** `post_links.target_url`, `stories.origin_url` and `posts.normalized_url` keep a gift link's token. Two posts linking one article, one by a gift link and one plainly, link two addresses: no link join, no shared root, two Discover lines.

**The rule:** an address compared (every `normalize_url`/`canonicalize_url`: link joins, story origins, dedup in `upsert_post` and 0122's `page_source`, Discover Pages and origins, 0114/0123 planning, `Origin.stored`) drops two kinds of query key, as it drops `utm_*` (0109 B1):
- **an access token**: a key naming a token, a gift, an unlock or access (`token|gift|unlock|access`, any case), or any key whose value is a signed token (a JWT, `eyJ….….…`). 0123's vocabulary, now in `url_normalization`;
- **a share mark**: a key that says who shared the page or from where, never which page: `smid`, `taid`, `mrfcid`, `srnd`, `leadSource`, `reflink`, `dib_tag`, and `syn-<8 hex>`.

**Kept for clicking:**
- `posts.url` and every post's HTML keep the address as written (as today).
- `post_links.shared_url` (new, migration 0073): the link's address as its post wrote it, when its normalized address dropped an access token or a share mark; else null.
- A story's outside origin carries `href`: the first member link's `shared_url` to it, else its address. The reader opens it (the origin line's Save page gets the gift link, so a page saved by hand from it is read as the owner's click would read it).

**Never fetched with a token:**
- 0123's walled test reads the members' links as written (`shared_url`): a page any member links by a gift link stays walled.
- Discover Pages (0113): a page linked by a gift link says "probably can't be read" (as before, when the token was in its address).
- 0123 stores no token (unchanged).

**Not in the rule** (ambiguous names, measured below; an open question): `r` (a newsletter platform's referral, but also a route or a viewport elsewhere), `rc`, `st`, `sh`, `share`.

### Measured (scratch copy `insight_server_1105_check_473857_a`, read-only source, nothing fetched)
Query keys of the rule in stored addresses (post_links targets and posts' normalized addresses; distinct addresses carrying the key, then how many become the same address as another stored one without it):

| key | kind | addresses | made one with another |
|---|---|---|---|
| unlocked_article_code | access | 69 | 1 |
| smid | share | 59 | 5 |
| syn-25a6b1a6 | share | 49 | 6 |
| accessToken | access | 31 | 1 |
| reflink | share | 26 | 0 |
| taid | share | 25 | 4 |
| view_token | access | 20 | 1 |
| leadSource | share | 16 | 1 |
| srnd | share | 13 | 3 |
| gift | access | 12 | 2 |
| dib (JWT value), dib_tag | access, share | 11, 11 | 0 |
| mrfcid | share | 9 | 3 |
| casa_token | access | 5 | 0 |
| access_token | access | 5 | 2 |
| giftId | access | 4 | 1 |
| ResultFunctionToken | access | 4 | 0 |
| guestAccessKey, pwapi_token, token | access | 3 each | 0, 1, 0 |
| sharing_token, shareToken, author_access_token, gift_content | access | 2 each | 0 |
| gift_token, sharingToken, jsc_token, ranking_info_token, giftid | access | 1 each | 0 |

- **327 addresses carry one; 40 groups of 83 addresses become one address** (77 link targets, 7 posts' own addresses).
- Posts whose own address carries one: **61** (13 keys; e.g. 21 unlocked_article_code, 13 view_token, 10 accessToken). Their `normalized_url`/`canonical_url` are rewritten by the migration; `url` keeps the token.
- `stories.origin_url` with a token on the copy: 0 (the owner's case came after the export).
- Not adopted, for the owner: `r` 260 addresses / 54 made one (236 on newsletter post pages, but also a map viewer's region, a router's route); `rc` 130 / 16 (one news site's share code); `st` 56 / 2 (one paper's share token, a library's view type); `sh` 15 / 0; `share` 3 / 0.
- On the copy as stored (rule applied to the keyed addresses only): **295 links in 212 posts change address; 57 posts' own compared addresses**; 26 addresses gather more sources than before, **22 reach 2+ sources for the first time** (the joins the rule can add). Story-level changes: the real-data check (below).

## 2. A collected page shows only inside its story
**Today:** a page Collect originals stored is an unread post of Saved, in the Main feed and Saved's counts.
**The rule:** the originals service marks it `metadata.story_only` (with `collected_original`, as 0123 marks it). A `story_only` post is no row of the Main feed, a track, or a source's list (Saved's), and no unread count. It stays:
- its story's root in the story, News and tree views (the lead among the posts a feed shows is the next post);
- its post page; Later, Kept and History when you put it there (search lists what the feeds list).
**Saving it by hand** (the save path finds it stored) drops `story_only`: it is in Saved as any page you save. A feed of a source you follow bringing the page later (0122's move) drops it too: it is that source's post.
Nothing is deleted or moved. No collected page exists before this ships (0123 is off on the server and the lab).

## 3. The quoted tweet's link
**Today:** Nitter's quote card cites the quoted tweet (`<cite><a href=…/status/…#m>`, kept as an x.com link: 0 of 2,662 quotes on the copy lack it), but the reader drops the card's footer, so the post page shows "Name (@handle)" and no address.
**The rule:** the post page, and a thread's replies, show the card's byline as "Name (@handle) · open post ↗", the link the quoted tweet's x.com address (`post_parts.quoted`), never the Nitter host. Only when the byline's handle is the quoted tweet's account. Feed rows show no quote card (their text drops the byline: unchanged); story trees name the quoted post when it is stored (unchanged).
**Measured** (the copy): 2,662 Nitter quote cards with a byline; **2,662 get the link** (every byline names its quoted tweet's account).

## 4. Collect originals: on by default
- **Found while building:** 0123's job read the setting from a `scheduler` row nothing writes (the dialog writes
  `scheduler_config`), so the switch never reached the job. Fixed: the job reads `scheduler_config` (a test pins the two).
- The scheduler's settings default `collect_originals` to on (`OperationsService`, `originals_service.collect_on`).
- An owner's choice is kept: a stored `true` stays on; a stored `false` written by this version or later (the row carries `collect_originals_default: "on"`) stays off. A stored `false` written before (when off was the default, so the dialog wrote it whether or not you touched it) reads as the default, on.
- No migration: the setting is read on each run.

## Discover and a collected page's site (answer, no build)
- **Pages (0113): no.** A Pages row is a story root no post is at (`Origin.stored`). Once collected, the root is stored
  (its post is the Saved source's), so the row, and its "Follow site…" button, leave Pages.
- **Suggestions: yes, as before.** `discover_rules.origins` puts a story whose root is on a site you don't follow in
  `suggest[site]` whether the root is stored or not. The collected story still counts toward that site's card
  ("N stories started there"), under the same bar (2+ pages, 3+ voices) or by links; Follow there is Discover's
  follow (feed finder and page watching). A single collected page alone doesn't make a card.
- Not built: a "Follow site…" on the collected page's post page. An open question.

## Built (2026-11-07)
Commits: 335f3ac (4: on by default; the job reads `scheduler_config`), 40922f4 (2: `story_only`), b149e97 (3: the quote's link),
3efd48c (1: tokens and share marks; migration 0073). Main v10.1 (8feb8c9) merged before.
- `utils/url_normalization.py`: `is_access_key`, `is_query_mark`, `has_query_mark`, the share marks; `_normalize_query` drops them.
  `utils/originals_rules.py` reads the same vocabulary (`tokened`: access tokens only), and `collect_setting`.
- `utils/post_links.py`: `PostLink.shared` (a later gift link to the same page is kept too); `repo_stories.write_links` writes `shared_url`.
- `db/repo_reader.py`: a story origin's `href`; `NOT_STORY_ONLY` in every feed scope (not Later, Kept, History) and the unread counts.
- `services/originals_service.py` (walled test reads `shared_url`; `scheduler_config`), `services/stories_service.py` +
  `repo_discover.gifted` (Pages: a gift-linked page "probably can't be read"), `services/saved_service.py` (`story_only` set;
  a hand save drops it), `db/repo_posts.py` (`drop_story_only`; a move to a followed source drops it),
  `services/operations_service.py` (the default, `collect_originals_default`), `utils/post_fields.quote_byline_linked`,
  `services/post_detail_service.py`.
- Frontend: the Scheduler switch on by default; `originHref` opens `href`; the quote byline renders as a link (inside INSIGHT when stored).
- Tests: `test_access_tokens.py` (new, 7), `test_story_originals.py` (+2), `test_save_fetch_first.py` (+1), `test_x_connections.py` (+1),
  `test_post_fields_utils.py` (+1), `test_operations_service.py` (+3), `test_stamps.py` (+1, the stamp case), `test_post_page.py` (href);
  `schedulerDialog.test.tsx` (2), `PostDetailPage.test.tsx` (+1), `story.test.ts` (+1). Backend 1,982 tests (one failure, fixed and
  re-run: the origin's new `href`), frontend 760 + node tests, build +11 bytes.

**The real-data check** (`scripts/realdata-check.sh --base main --head 3efd48c insight_lab`, report
`plan/research/lab/checks/3efd48c-2026-11-07.md`): **PASS**, no case changes state, no invariant rises (deploy start and identity 0),
0 News lead changes. Diff: 11 posts joined a story and 1 story gained a post (each read: a gift or share link, or a post whose
own address had a token, now at the same article as its partner: the lab's news-site share links, a newsletter's gift link, a
syndication mark); 1 News row 4 -> 5 voices (the same); 6 roundup counts; 74 Discover lines moved; story origins, titles, Classics unchanged.

## Handoff (2026-11-07)
- Branch `issue-0126-originals-owner-decisions` in worktree `.claude/worktrees/agent-ae4760bf3a416f92c`, main (v10.1, 8feb8c9) merged.
- Built and committed: all four items (above).
- Measured: the key table above (scripts outside the repo, `/tmp/i0126/keys.py`, `tok.py`, `join.py`, `rkeys.py`).
- Left: the owner's merge.
- Running: nothing; the scratch copy `insight_server_1105_check_473857_a` was dropped.
- Open: the ambiguous keys (`r`, `rc`, `st`, `sh`, `share`); whether a page saved by hand from a gift-link origin may be read with its token (built: yes, the owner's click).
