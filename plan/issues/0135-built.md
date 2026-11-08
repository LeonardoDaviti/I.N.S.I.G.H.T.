# 0135 Built: new spheres, the silent failures

Built 2026-11-08 on its own branch, test-first. No migration (0084 unused). Everything below is unit-tested
from fixtures (invented hosts, no request leaves the test): `insight_core/tests/test_new_spheres_0135.py`,
plus `frontend/src/components/AddSourceModal.test.tsx`.

## Per failure

| # | Failure | What changed |
|---|---|---|
| 1 | RSS 1.0 (RDF) stores nothing | `parsing.parse_feed_posts` reads `rdf:RDF/item`: title, link (else `rdf:about`), description / `content:encoded`, `dc:date` / `prism:publicationDate` (a date alone is `date` precision), `dc:creator` into `metadata.authors`. `parsing.ITEM_PATHS` is where each shape keeps its items; the feed finder reads candidates by the same paths and refuses a feed whose items are elsewhere (`FeedFinding.refused`, "this feed has items INSIGHT can't read"; the dialog says "Not added: …" and Add stays off). |
| 2 | An empty fetch looks healthy | `kinds.base.EmptyFetch` / `checked_fetch`: "the feed has N items but 0 were stored" (generic RSS) and "every item was skipped (N videos): 14 the bot check, 1 timed out" (YouTube, skip reasons counted from yt-dlp's error) are fetch errors: source health shows `last_error`, the failure count and backoff apply, the summary counts the source (error, then backoff). Over half skipped is `FetchOutcome.warning`, logged and in the job line ("· warning: 12 of 15 videos skipped: …"). The source doctor records `{empty_fetch, note}` for any kind and looks for nothing (never "working again"). |
| 3 | Transcripts prefer English | `youtube_service.transcript_tracks`: the video's own language first (`language`, else the default audio track's, kept before the formats go, else the `<lang>-orig` automatic track), its subtitles, then its untranslated automatic track; then the preferred list, with an automatic track only in the video's language. A translated automatic track is never taken while the video has a language. The post carries `language_code` from the stored track (`post_fields` takes a kind's declared language) and `metadata.video_language`. |
| 4 | Raw caption XML stored | `plain_transcript`: a payload is read by its content, not its declared ext (srv1/srv3/ttml XML by its `<text>`/`<p>` cues with escaped markup decoded, json3, WebVTT with its header and inline tags gone, repeated rolling lines once). |
| 5 | Telegram dated by edit time | `telegram_rss.message_order_dates`: a bridge post dated after a post numbered after it takes the earliest of those dates (carried across a fetch's pages); the bridge's date stays in `metadata.bridge_date`. The MTProto path reads Telegram's message date (`synthesize_posts`, tested with an `edit_date`). |
| 6 | A search feed taken as the journal's | `feed_finder.is_search_feed` (title words search/query; `?q=`, `?term=`, `?s=` …; a `/search/` segment): ranked after the site's own feeds; the answer marks it `saved_search` and the dialog says "A saved search, not the site's own feed". |
| 7 | Blocked journal pages | A page answering 401/403/429 has `/feed`, `/rss`, `/feed.xml`, `/rss.xml`, `/atom.xml` tried under the page itself, then at the site's root, first, through the finder's own fan-out, timeouts and budget. A pasted feed address is still "feed" (tested with an RDF feed). |
| 8 | No bridge on a fresh install | `TELEGRAM_RSS_HOSTS` (hosts or origins; the first is used; unset: `https://telegram.local`, as before; set empty: none). `GET /api/sources/telegram-bridge`; the Telegram template builds on it, or says no bridge is set and adds nothing. `.env.example` ships it empty. Every listed host is read as a bridge beside the known ones. |

## The repair (`scripts/repair_0135.py`)

Run by the ingestion process at each start (`run_scheduler`, a thread, logged), and by hand
(`--dry-run`, `--dates`, `--transcripts`, `--limit`):
- dates: each bridge source's posts out of message order put back, the old date in `metadata.bridge_date`; no request;
- transcripts: a stored automatic track in another language than the video's (`metadata.video_language`, else a
  Cyrillic or Georgian title: the stopword guess reads English titles as Portuguese) or caption markup, read again
  through `_build_video_post`, 10 a start, 3 s apart, never with yt-dlp off, stopped by a bot check; each post tried
  is marked `metadata.transcript_repair_0135 {from, why, chars, at, result}` (resumable, once each).

## On the server copy (insight_server_1105, a scratch copy, dropped)

- Transcripts: 1,218 stored videos; **5** due: 4 Russian videos stored as YouTube's English translation (`automatic_captions:en-US` / `en`), 1 English video with a look-alike Cyrillic letter in its title (re-read, kept as it is). **1** stored as WebVTT markup (one of the 4); **0** raw XML.
- Telegram dates: the server's own bridge, 36 sources, 17,106 posts: **0** out of message order. The edit-time dates came from the public bridge the research used. MTProto: 4 sources, 0 posts on the copy (nothing to measure).
- "Empty, not healthy": 23 enabled sources last fetched "empty" (19 feeds, 4 YouTube channels), every one with stored posts. Which are now errors needs a fetch: a feed's "empty" also covers an unchanged answer (304).

## Not verified until the server or the lab fetches

The 5 journals' RDF feeds and the YouTube bot check on the Starting Point instance; whether a blocked journal's
`/feed` paths answer (the research's working feed addresses were deeper ones); the bridge's own date fields
(no bridge answer was read here); the transcript repair's re-reads (yt-dlp, from the server).
