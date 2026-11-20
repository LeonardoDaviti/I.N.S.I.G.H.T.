# 0254 — v10.28: ingestion after the v10.27 deploy

Four bugs seen on production after v10.27. Tests with invented data only:
`tests/test_ingestion_after_deploy_0254.py`; updated `test_ingestion_health_0242` (the stalled dict),
`test_new_spheres_0137` (a feed with one broken item is now offered; one broken outside its items is still refused)
and `stoppedSources.test.tsx`. Module runs: 555 + 209 tests, the full suite not run (one run per merge). No migration, no stored state.

## 1. Feeds whose items share one link
**What I found first.** The two production messages ("42 items share 1 address", "888 items share 2 addresses")
are exactly what the parser before v10.26 says. I read the two public feeds once, read-only, no server data:
Unsloth's changelog links `…/changelog#<release>` with the same string as a non-permalink guid; PHP.net's Atom links
`index.php#<id>` with `<id>` `archive/<year>.php#<id>`. Both are URLs with fragments, the 0242 case; today's parser
gives them 42 of 42 and 892 of 899 addresses (7 true duplicates), and no failure. So the stored reason is from a
fetch before v10.26; the next fetch (or a forced one) should clear it. **Owed on the server**: one forced fetch of
each, and its outcome.

**The class, fixed in `parsing._identities`.** When most items link one page, each item already gets an address of
its own: the feed's address with the item's guid (any string), else its title and date, as `?insight_item=` (the
existing `item_address`, the same at every fetch). Not `link#guid`: `normalize_url` drops fragments, so those
would fold back into one post at the save. The gap that was left: a guid **every item shares** (a news feed whose
guid is its home page) was the token for all of them, one post, silently. Now a guid that items with another title
or date share names no item: each is known by its enclosure, else its title and date. True duplicates (same guid,
title and date) stay one post; items with links of their own are untouched.

**Items stored before.** Nothing is rewritten. Items whose address does not change (links of their own, distinct
guids) keep their posts. The only items whose address changes are those of a feed whose every item shared one guid:
before, all of them were one post at `?insight_item=<that guid>`; that post stays, and the items arrive as new
posts at `?insight_item=<title|date>`. For PHP.net, the 2 posts the old parser stored (at its 2 shared pages) stay; its items come at the feed's `?insight_item=<id>` addresses, as v10.26 already made them.

## 2. A whole feed failing on one malformed item
`parsing.read_feed` (`feed_root` is it): a document refused strict and repaired is cut into its items (from one
item's start to the next's), each parsed alone with the root's namespaces; a piece that fails is joined to the next
pieces that fail too (an item whose text holds `<item>`, `MAX_JOINED` 4); what still fails is skipped. The rest is
read only when the error was in an item (an item whole up to its closing tag with an error after it is the
feed's error, not the item's), at most half the items are broken (`BROKEN_ITEMS_SHARE`), and every other
item is read back; else the parser's first error, as before. A document that parses but holds more item starts than
items read (a CDATA left open runs into the next item and hides it, valid XML) is cut the same way: the broken item
is skipped and the hidden one comes back.
`parse_feed_posts` returns `FeedPosts` (a list) with `broken`; `checked_fetch(broken=)` warns
`1 broken item skipped: the item "X" (line 2189): unclosed CDATA section` — the fetch is a success with a warning.
daringfireball's real broken item is gone from its feed now (it parses, 48 items); tested on invented feeds.

## 3. "Stopped: never fetched" with posts
`operations_service.stalled_fields` carries `posts` (stored) and `reason` (the last error, when the last attempt
failed). `sourceList.stalledNote`: never a live success but posts → "Stopped: its live feed fails: <reason>" (no
reason: "its live feed has not worked yet"). The flag's rule is unchanged: the live feed has stopped.

## 4. Adding a YouTube or X source without a test read
`BaseKind.test_read` (None: nothing of its own to try) with `ReadCheck(reason, gone)`; `YouTubeKind` lists the
channel's newest video (`YouTubeService.test_read_channel`, yt-dlp, 45 s), `NitterRssKind` reads the account's
feed once through the bridge. `feed_finder.test_read` resolves the kind and runs it (60 s budget, never raises).
`POST /api/sources` (the Add dialog, Add several, Save page all use it) runs it first (not for a page to follow: its preview read it): `gone` (404/410, "does not
exist") → 400 "Not added: <handle> can't be read: <reason>"; any other failure (bot check, timeout, bridge down) is
added with `warning`, which the Sources page shows. A feed or page has no test read here: the finder and the
page-watch preview read it before Add, as before.

## Owed on the server
1. Forced fetch of Unsloth Changelog and PHP.net news: stored count, warning, no failure.
2. `GET /api/sources/health`: their `stalled` note reads "its live feed fails" until (1) clears it.
3. Re-add "Made with Layers" with the right handle; the wrong one is refused with yt-dlp's 404.
