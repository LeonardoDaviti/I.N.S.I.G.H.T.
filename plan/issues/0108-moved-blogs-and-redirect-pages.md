# 0108 — A blog that moved: follow a page's redirect, find the feed it moved to, read its older posts

Status: **built** 2026-11-05 on `issue-0108-moved-blogs`, not merged (Built, below); spec 2026-11-05, from a source the owner added (a personal site whose blog moved to its own domain). Measured on the server's stored posts and on the site's own pages, read once.

**Constraints:** download nothing beyond the measurement already made; tests use fixtures written from the pages' shapes (no real names in committed files); fix the class, never one site; nothing merges unless `scripts/realdata-check.sh` passes.

## What happened (server, 2026-11-05)
1. **Added the person's site; the finder took its first feed.** It found the site's own `feed.xml` (a Jekyll feed of 10 entries, 2018–2021) and stopped there.
2. **All 10 posts are stored with no text.**
   - The feed's entries have empty `content` and `summary`.
   - Each post page is a **redirect stub**, 574 bytes: `<meta http-equiv="refresh" content="0;url=…">`, a `<link rel="canonical">` and a `location=` script, all pointing to the same article on the blog's new domain (a Ghost site).
   - INSIGHT's client follows HTTP redirects, not these. The article reader read "Redirecting…", got under 700 characters, and kept nothing.
   - **No try was counted** (`read_article` returns None, and `_read` records nothing then), so 0062's read-again never picks these posts up. They stay empty forever.
3. **The real blog wasn't found.** The site's menu links to it (`href="https://askell.blog"`), but the finder's step 3 only follows blog links on the same site (a `blog.` subdomain), and it never reached step 3 because step 1 found a feed.
4. **The owner added the blog by hand.** Its RSS has 15 posts with full text (1.6–16.6k characters each), but its sitemap lists **22**. The 7 oldest exist only in the sitemap, and a feed source's archive doesn't read sitemaps (page watching does, 0028).
5. **The 10 empty posts duplicate 10 of the blog's posts** (their canonical address is the blog post), so the feed shows each twice.

## Decided
1. **The article reader follows a page-level redirect once:**
   - a `meta refresh` with a URL, or a `<link rel="canonical">` to another address, on a page whose own text is tiny (under 700 characters);
   - it reads the target, at most one hop, within the same budget;
   - the post keeps its own address and records the target as its canonical (`canonical_url`), so 0106's page aliases make the two one page, and stories and Classics count them once.
2. **A page read that yields nothing longer, on a post with no body, counts as a failed try** (`with_page_try(failed=True)`), so 0062 reads it again later. A post that has a body and a page with nothing longer is unchanged (no try counted: its feed body is the better version).
3. **The finder looks past a feed whose posts have moved:**
   - when the feed it found has entries with no bodies, it reads the first entry's page;
   - if that page redirects or is canonical to another site, it runs the finder on that site too;
   - it offers both, the moved-to feed first, labelled "the posts of this feed now live at <host>".
4. **The finder considers the home page's menu link named Blog (or Writing, Posts, Essays) on another domain,** as a candidate after the site's own feeds. Today only same-site blogs count. A link out to a platform (Medium, Substack) already counts through its platform rule.
5. **A feed source's archive reads the site's sitemap of posts** (`robots.txt` Sitemap lines, `/sitemap.xml`, and a sitemap index's post sitemap) when the feed holds fewer posts than the sitemap. It reuses page watching's sitemap reader, and each older post's article is read the way the finder's articles are. Keep everything: nothing stored is removed.
6. **The source with moved posts says so** on its row: "Its posts now live at <host>: follow that instead?" The owner chooses. Nothing is disabled or deleted by INSIGHT.

## Done when
- Fixture tests: a redirect stub (meta refresh; canonical only; JS only, which isn't followed, and the post counts a failed try); a feed of empty entries whose pages redirect to another site's feed; a menu Blog link to another domain; a Ghost-shaped sitemap with more posts than the feed.
- On the server after deploy: the old site's 10 posts are read again and alias to the blog's posts (one post each in the feed); the blog's archive reaches 22 posts. The owner checks; nothing is fetched from this machine.
- The real-data check passes; its diff lists only these.

## Built (branch `issue-0108-moved-blogs`, 2026-11-05)
From main 2a1a6f8; not merged, not pushed. No migration. Nothing fetched or downloaded: every rule is tested with fixtures written from the measured pages' shapes, and replayed once (privately, in a container with no network) on the pages read for the spec.

1. **A redirect stub is read where it points** (`parsing.moved_to`, `full_text.read_article`, `STUB_PAGE_CHARS` 700):
   - a page whose read text is under 700 characters and that names another address (a meta refresh's URL, else a `<link rel="canonical">` to another address by `normalize_url`) is read at that address, one hop, with the same client; a `location=` script alone is not followed; a long page with a canonical elsewhere is read itself.
   - The post keeps its address. Its `canonical_url` is the target and `metadata.moved_to` the target normalized (`post_fields.MOVED_KEY`); a feed re-fetch keeps both (the upsert keeps `moved_to` like `page_tries`, and the canonical with it), and the repair's `save_full_text` writes them.
   - **One page** (`story_rules.page_aliases`, `keys`; `StoryPost.moved_to`, read by `load_posts`): the old address is an alias of the moved-to one, so the old post and the post stored there join by address (one story: the feed shows the pair once), a link to either is a link to the stored post, and the old post holds `u:<moved-to>` so the incremental job regroups it with that post. The stamp's sample has a case (`m1`, `m2`), so the first start regroups every story (as 0106).
   - **Classics** (`NewsService._cited`, `NewsRepository.moved_pages`, `moved_paths`): a link to the old address cites the post where it moved; a batch touching either address rewrites both.
2. **An empty read of a post with no body is a failed try** (`full_text.empty_read_failed`): a new post (`_read`), a read again (`_read_again`: it stays failed until the third try) and the repair (`_write(failed=True)`, so not marked checked). A post with a body and a page with nothing longer counts nothing, as before.
3. **The finder looks past a feed whose posts moved** (`feed_finder._past_moved`, `Feed.bodiless`, `Feed.moved_to`): when the first feed found whose entries carry no body (no description, summary or content with text) has a first entry whose page lands on (HTTP) or names (meta refresh, canonical) another site, the finder runs on that page; its feeds come first, the old feed after with `moved_to` (the site), and the status is `found`. The answer's feed rows carry `moved_to` (`where_linked.feed_row`), and Add source shows "The posts of this feed now live at <site>" under the old feed.
4. **A menu blog on another domain** (`_elsewhere_blogs`, `_with_elsewhere`, `ELSEWHERE_BLOG_TEXTS`): the home page's header, nav or footer link whose words are exactly Blog, Writing, Posts or Essays, on another site, at most two: a platform's feed by its rule (Medium), else the feeds its page names (or the page, when it is a feed); they come after the site's own feeds, or are the finding when it has none. A link so named in the page's text is not a menu link and is not read.
5. **A feed's archive reads the post sitemap** (`GenericRssKind.inspect`, `archive_pages`, `checkpoint_resumable`, `feed_section`; `page_watch.sitemap_entries(posts_only=True)`):
   - the feed's section is the folder its items share, a date's folders aside (`/posts/` for `/posts/2021/03/a`; `/` for a Ghost blog's `/slug/`); the sitemap is page watch's (robots.txt's Sitemap lines, else `/sitemap.xml`), an index read for its children naming posts only (not pages, authors or tags);
   - when the sitemap lists more of the section than the feed holds, `inspect` counts both (`available_posts`; `raw.sitemap_posts`), and the archive yields the feed (one page), then each older post read from its page as page watch reads one (body, title, the page's date, else the lastmod; no post without a date or `og:type` article), marked backlog, one per archive page (the host gate spaces them). Its checkpoint (`mode: sitemap`, the site, the section, `next_index` into the sitemap's posts, newest lastmod first) resumes a paused archive; a stored post or a feed item is skipped, never read. A feed holding the whole sitemap, or a site without one, archives as before (one page, no checkpoint). Nothing stored is removed.
6. **The row says so** (`repo_fetch_state.moved_to`, `MOVED_NEWEST` 10; the health row's `moved_to {host, followed}`): when half or more of a source's 10 newest posts (feed order) moved to one other site. The row's note (first, before quiet) and the source's sheet say "Its posts now live at <site>: follow that instead?", or "…, which you follow too" when a source of yours is at that site. Nothing is switched off.

**Replayed on the real pages** (private, `plan/research/0108-build/HANDOFF.md`): the stub is named moved to its blog post (its own text reads 0 characters); the old feed's 10 entries are bodiless; the home page's menu "Blog" is its blog elsewhere (the site's own feed is found first); the blog's 15 feed items share the section `/`, and the blog's real sitemap gives **22 posts, 7 older** than the feed.

**Measured on the lab** (read-only):
- No stored post has `moved_to` (nothing moved is stored there: the case's post is not on the lab), so stories, Classics and rows are unchanged (the check's diff, below).
- `canonical_url` alone could not be the marker: 31 lab posts already differ from their address (a query's `%2F`), all on their own host.
- 7 generic RSS sources hold 566 posts with no body (feeds of titles only whose pages read nothing longer). From now on a *new* such post counts failed tries, so it is read up to twice more, a day apart (decision 2); the stored ones are untouched (no try counted). Their feeds are bodiless, so adding one again reads its first entry's page once (64 KB).
- The row's query: the 10 newest posts by the feed-order index, 28 ms over the lab's 247 sources (by `fetched_at` it sorted every post: 59 s cold).

**Tests** (written first, each item red before its code): `test_moved_pages` (32: the stub's three pointers, one hop, a long page with a canonical, the store keeping the move on a re-fetch, the repair writing it, the story job reading it; one page, one story, a link to the old address, the key; an empty read counted on a new post, a read again and the repair, a post with a body not; the row's `moved_to`, followed or not, half the newest; Classics in a full run and a batch), `test_feed_finder` (13 more: a moved feed from the home page and from its own address, an HTTP redirect, a feed with bodies, a same-site canonical, an unreadable entry page, the route; the menu blog elsewhere after the own feed, alone, each word, not in the text, another word, a platform, both ways at once; 3 request counts now include the first item's page of a feed of titles only), `test_sitemap_archive` (10), `test_stamps` (the sample's move; dropping it changes the stamp). Backend **1,516 OK** on the final head (`./run-tests.sh`, own image tag; one search test, `test_search`'s dates competing, failed once at item 4 under the machine's load and passes alone and in every later run). Frontend: `npm test` 229 node + 709 vitest, `npm run build` within the gate (feed route 172,910 bytes gzip, 0.07% over its baseline, within; the Sources chunk carries the row's note).

**The real-data check** (`scripts/realdata-check.sh --base main --head issue-0108-moved-blogs insight_lab`): **PASS**, no `--allow`, on head e786e03 (and once before on f50ea3e, the same). Report: `plan/research/lab/checks/issue-0108-moved-blogs-2026-11-05.md` (private).
- Cases: 75 pass, as main; none changes state. `blog-body-empty-after-page-read` stays failing on the lab: its post is not there (the source was added on the server after the lab's copy); it can pass only on the server, after the repair (below).
- Invariants: every one equal to main; `story.identity` 0 of 743,865 rows, `story.rebuild_identity` 0.
- The diff: **empty** (titles, text starts, link titles, roundups, story membership and origins, News, Classics, Discover: 0). As expected: no lab post has moved, so no rule fires; the stamp's new sample case changes only the stamp (both sides run the full job).

**What the owner will see on the server** (nothing is fetched from this machine):
- The first start regroups every story (the stamp).
- The old site's 10 posts are stored with no try counted, so no fetch reads them again: run `python -m insight_core.scripts.repair_full_text --source <the old site's source id>`. Each is read at the blog's post (2 requests, 2 s apart), stored with its text, `canonical_url` the blog post and `moved_to`; the next story job joins each with the blog's post (their dates are the same days): **one line each in the feed**, both sources named. Case `blog-body-empty-after-page-read` should then pass.
- The old source's row then says "Its posts now live at <the blog>, which you follow too".
- The blog's archive (Archive on its source): planning counts 22 (15 in the feed, 7 in the sitemap); the archive reads the 7 older posts one page each and the source reaches **22 posts**.
- Adding the old site again (or any site shaped so) offers the blog's feed first, the old feed after with "The posts of this feed now live at <the blog>".

## Left open
- **A small sitemap can still be refused**: the archive service refuses a feed source whose `available_posts` is at most one live fetch's limit (20 by default) ("This feed only lists its latest N posts"). A blog whose sitemap holds 16-20 posts is refused though its archive would read more. The fix is in `services/source_fetch_service.archive_support` (0107's file): don't refuse when `settings.archive.sitemap_posts` is over 0. Not needed for the measured case (22).
- A news site's archive can be long: its section is often `/` (date folders aside), and an index without children naming posts is read to 5 files (5 MB each). The archive is the owner's choice and paced by the host gate.
- The 10 stored posts need the repair once (above): nothing recorded that their read found nothing.
- The real-site check is on the server: the stub's target pages, the blog's RSS and its older posts' pages were not read here.
- Which of the pair leads its story is by time (the same day): the old site's post may lead with the blog named beside it.
