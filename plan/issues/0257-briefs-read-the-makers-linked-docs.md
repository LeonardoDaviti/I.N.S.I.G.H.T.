# 0257 — Track briefs read the maker's linked docs (v10.30)

Status: **built, ON** (`entity_bands.json` `tracks.linked_docs`, default true). Not yet measured on real data: the
main session's real-data check is the first look at how many track posts have a stored maker page.

## Why

The general track briefer (0245/0249, `markx/track_things.py`) read a post's text plus its links as a list only.
Release notes are often terse ("add network permission toggle") and link the maker's own page that explains the
feature (a project's changelog linking its docs, a release linking `features#...`). The fields a reader wants (what it
does, its numbers, its limits) are on that page, so the briefer left them empty or guessed nothing.

## What INSIGHT already stores (searched first)

- **`posts`** is where a linked page's text lives: a page INSIGHT has (a followed source's post, a saved page, an
  original collected by the originals step: story_originals kinds `collect`, `entity`, `cited`, `linked`) is a post
  at its address, read through `tasks.load_posts`. 0208 already reads a link post with its shared page this way.
- **`post_refs`** (0076/0125) holds every http(s) link of a post's text, its own site's included, normalized as
  `posts.normalized_url` is; Connected's Earlier resolves them to stored posts by that address. **`post_links`**
  leaves out a post's links to its own publication (`linked_rules.own_links`), so it cannot find the maker's pages.
- Fetching: 0084 B / 0114 (`repo_linked.linked_not_stored`, `fetch_linked`) already fetches a followed source's own
  pages that stored posts link, through the normal fetch path (host gates, budgets, backoff); the originals step
  (story_originals) collects other pages under its credit.

**Choice:** read only. `maker_pages` takes the post's `post_refs`, keeps the ones on its own site, resolves them to
stored posts by `normalized_url` (as Earlier does) and loads them with `tasks.load_posts(linked=False)`. Nothing new is
fetched or stored here, so there is no parallel fetch path and no new table. A maker page INSIGHT does not hold yet is
not read (see "Not done").

## Built

- `maker_page(own, link)`: the link is on the registrable site of the post's own address (`addresses.site_of`); on a
  site of accounts (`addresses.PLATFORM_SITES`, `rename.CODE_HOSTS`) it must also be the same account
  (`addresses.account_key`), so a code-host release linking its own repo's docs counts and a link to another repo
  does not. No site is named.
- `maker_pages(cur, posts, own)`: at most **LINKED_DOCS = 2** stored maker pages a post, in the post's link order,
  never the post itself or its own address, not a source's signature (`post_refs.boilerplate`), only open refs.
- `things_inputs(..., pages)`: the post's own questions are unchanged byte for byte; then one question a page while
  all of a post's questions stay within **MAX_WINDOWS = 6**. A page's question shows the post's first
  **LINKED_POST_CHARS = 1500** characters and its links, then `Linked page on the post's own site: <url>`, its title
  and **WINDOW_CHARS = 3500** of its text, starting **LINKED_LEAD = 200** characters before the words the link's
  anchor names ("#fast-decode" -> "fast decode"), else at the start. Its `Window: k of n` line gives it its own
  report window. The post's own address is replaced by OWN in the page text too, so it is never offered.
- `salvage`: unchanged checks: every quote must be in what the question showed (now with the page). A value whose
  quote is only in the page (not in the post part) gets `"page": <url>`; kept in the report's `field_values` (jsonb),
  carried by `remerge` into the row's fields and by `track_brief.thing_view` into the API. No migration.
- The guide `track-things-v1` is unchanged (a changed guide body is refused under the same id); the page is shown
  inside POST, labelled, so "quote from the post's text" covers it.
- Planned only for posts not yet asked under the schema version (as before): posts already asked are read with
  their pages after the next schema version.

## Why default on

Tested (`tests/test_track_linked_docs_0257.py`): with pages the post's own questions are identical to the questions
without them (short and long posts), so every existing question and its task (same input hash) stands; pages only
add questions, a value quoted from the page is checked like any other, and a question with no page salvages as
before (no `page` key). Off: only the post's own questions.

## Not done

- Fetching a maker page INSIGHT does not hold. The existing path that would (0114 / 0084 B `linked_not_stored`) only
  takes a followed source's pages that match its post-page shapes (`linked_rules.OwnPages`); docs/features pages
  usually don't, and `official.pages_wanted` excludes docs pages from 0196's cited pages. Widening that is the
  originals step's decision (a new `story_originals` kind would need migration 0167), not the briefer's.
- Not measured on real data (how many track posts link a stored maker page, and how many fields it fills).
- The frontend does not show `page` yet (the API carries it).
