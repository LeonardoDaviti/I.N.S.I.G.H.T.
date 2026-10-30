# 0057 — A link to a post you already have opens it in INSIGHT

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "can we replace links in the post with the links of the post from our insight, because I don't want to leave platform").

## The case
- **Example:** data_secrets' post `t.me/data_secrets/10206` links `t.me/data_secrets/9951`, which INSIGHT has stored. Clicking it leaves INSIGHT for Telegram.
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
