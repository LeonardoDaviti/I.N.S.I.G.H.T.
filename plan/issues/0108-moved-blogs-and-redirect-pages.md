# 0108 — A blog that moved: follow a page's redirect, find the feed it moved to, read its older posts

Status: **spec** 2026-11-05, from a source the owner added (a personal site whose blog moved to its own domain). Measured on the server's stored posts and on the site's own pages, read once.

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
