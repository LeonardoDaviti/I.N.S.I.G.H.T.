# 0057 — A link to a post you already have opens it in INSIGHT

Status: **built, not deployed** (2026-10-31) for v9.8 (owner, 2026-10-31: "can we replace links in the post with the links of the post from our insight, because I don't want to leave platform").

## The case
- **Example:** data_whispers' post `t.me/data_whispers/10206` links `t.me/data_whispers/9951`, which INSIGHT has stored. Clicking it leaves INSIGHT for Telegram.
- **The class:** every link in a post's text to a page INSIGHT has stored (an earlier post from the same channel, a blog post your sources cite, a classic).
- **A catch:** links back into the post's own platform (Telegram to Telegram) are not kept in 0050's post links, so the lookup can't rely on them.

## Decided
- **When showing a post, each link in its text whose address is a stored post opens that post in INSIGHT.**
  - The match uses the cleaned-up address (0049's normalizer), and the stored post is the first seen when several share it (0049).
  - A small ↗ beside such a link opens the original.
  - A link to a page INSIGHT doesn't have works as today.
- **Computed per post when it's shown:** the post detail returns the links that are stored posts, looked up directly by address, so same-platform links count too. No new table.
- **Applies everywhere a post's text is shown:** the post page and continuous reading.
- **Out of scope:** rewriting stored HTML, and links inside feed excerpts.

## Done when
- **Backend tests:** a same-platform link, a cross-site link, a link to a page not stored, a URL form variant (tracking tags, a fragment), and two posts at one address.
- **Frontend tests:** an internal link navigates inside INSIGHT, and ↗ opens the original.
- **Lab case** `internal-link` passes.
- **Checks:** bundle within budget.

## Built
- **Backend** (no migration, no new table):
  - `utils/post_links.body_hrefs`: every link target of the post's text as the reader gets it: the HTML's hrefs (entities decoded; escaped HTML such as Reddit's is decoded first, as the reader does); with no HTML, the bare addresses of the plain text, trailing punctuation dropped. Any platform, the post's own included; at most 500.
  - `PostDetailService.internal_links`: each href made absolute against the post's url and normalized (0049), then one query: the post with that exact url, else the first seen at its normalized address (`fetched_at`, `created_at`, `id`), never the post itself.
  - The post detail returns `internal_links`, `{href as written: post id}`.
- **Frontend:**
  - `MarkdownRenderer` takes `internalLinks`. Such a link becomes a router link to `/posts/<id>`, in the same tab, with a small `text-3` ↗ after it (`Open the original`, a new tab). Any other link is as before.
  - The post page passes them for every post it shows, so continuous reading has them too.
  - `MarkdownRenderer` is not in the reader's initial JS.
- **Tests:**
  - Backend `test_post_page.py`:
    - `body_hrefs`: HTML, escaped HTML, plain text;
    - a same-platform link (t.me to t.me), another site, a page not stored;
    - another form of the address (`http://www.`, `utm_*`, `&amp;`, a fragment);
    - two posts at one address: the first seen, or the exact url;
    - a relative link, plain text, not the post itself, malformed links.
  - `test_post_detail_reader.py`: the route returns `story` and `internal_links`.
  - Frontend `PostDetailPage.story.test.tsx`: an internal link navigates inside INSIGHT and opens the post; ↗ opens the original in a new tab; a link to a page INSIGHT doesn't have and a post without internal links work as before.
  - Suites (with 0055): backend 999 OK; frontend 181 node + 645 vitest, typecheck, lint, build OK.
- **Bundle:** the reader's initial JS stays **479,685 bytes** (+0).
- **Lab case `internal-link` passes** (on `insight_lab`, read only): `t.me/data_whispers/10206` maps `https://t.me/data_whispers/9951` to the stored post.
  - Over the latest 3,000 posts, 407 link a stored post (722 links), 560 of them to the post's own site (LessWrong, Nitter, METR, Telegram channels, blogs).
  - A sample of 15 was right every time, including `#block-element` and `#m` fragments.
  - The lookup takes 0.4 to 0.8 ms a post.
- **Screens:** the `story` frame's link with ↗, light and dark: `~/.cache/insight-checks/0055-0057-shots/story.*.png`.

## Left open
- **The exact url comes before the first seen.** When a link's exact url is stored, that post opens even if another post shares its normalized address (Daring Fireball's `#fn1-` posts); otherwise the first seen opens, as 0049 says.
- **The match is on the href as written.** The renderer gets the same href from the same HTML. A link the renderer reshapes would not match and would stay external; none was seen.
- **The ↗ is small** (about 0.85em), with no bigger target on touch screens.
- A link to a stored home page (a watched page) opens it in INSIGHT too: it is a stored post.
