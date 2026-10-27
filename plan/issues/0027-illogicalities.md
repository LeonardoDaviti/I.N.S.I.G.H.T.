# 0027 — Illogicalities: controls and words that contradict their place

Status: **discussion** (owner, 2026-10-27): found by an audit of every page on the local preview, each confirmed in code. The owner picks what to fix. Already fixed: Stream / By source and the flow choice on one source's page (3d9d21d).

## Real bugs behind the words
1. **Archive catalog and its refusals.** The catalog lists every enabled source, including the 38 that can't archive ("No archive" only once opened). The refusal "every fetch already reads up to 50" is false: `get_source_by_id` reads no settings (`repo_sources.py:23`), so the check always uses 50, while RSS fetches 20. A feed listing 30 posts (Solos Glasses Blog) has 10 archivable posts but is refused (`source_fetch_service.py:92-160`).
2. **"Max posts per fetch: Not enforced yet"** is false: it is enforced (`ingestion/schedule.py:184,286`, `runner.py:313`; live 20 RSS / 5 YouTube / 25 Reddit). The field is disabled, yet the sheet's Save sends it (50 when unset, `SourceSettingsEditor.tsx:117,206`) and templates send theirs. Decide: a real editable setting, or no field and stop sending it.
3. **A track's "In main feed and digest" ✓** reads the track's own stored flag, which nothing else reads (`main.py:806`); AI Papers shows ✓ while all 3 of its sources are out of the main feed (`SourcesConfig.tsx:282-287`). Derive it from the member sources (mixed when they differ).

## Remove
4. Ingestion → jobs: 38 of the 50 recent jobs are retired analysis jobs ("Vertical briefing source", "Analyst inbox rebuild"; `operationsOverview.ts:13-19`, kept by `0027_drop_analysis.sql:9`). Filter or delete them.
5. Add source: the one-address templates (LessWrong, Gwern, Dario, Pipecraft, The Batch, Cloud Attention, ZTM) show an "Archive Scope" field that changes nothing and disables the URL field; their help is jargon ("custom … adapter", "sitemap-backed"). No field; one plain sentence.
6. Reddit post page "Fetch comments" always fails (403, `reddit.py:167-171`); the Reddit archive Plan too (`reddit.py:125`). Hide both (0012, 0025).
7. Connections: the Reddit and YouTube rows say "Not needed" twice, can't open, and Reddit's is untrue (`credentials_service.py:80-81`). Remove.
8. ⌘K "Source health" opens the same list as "Sources" (`navigation.ts:81`). Remove.

## Hide in context
9. Starred view: the subtitle "1,890 unread" (All posts' count) above "No starred posts" (`ReaderPage.tsx:162,177`).
10. A disabled or unavailable source's sheet still shows cadence, override, main-feed switch and a grey Fetch now, and repeats its Connections hint (`SourceSettingsEditor.tsx:240-316`). One line instead.
11. Shortcut help on a post without `?ctx=` lists j/k, which are unbound there (`PostDetailPage.tsx:496-497`).
12. Continuous post page ends with "You're all caught up" under All or Starred; say "You've reached the end" unless Unread, as the list does (`PostDetailPage.tsx:472,554`, `FeedList.tsx:345`).
13. On `/read/source/<id>` every row repeats the source name, linking to the page you're on (`FeedItem.tsx:200-206`).
14. Sources chips: "Unavailable 0" always shows; "Backoff" repeats part of "Failing" (`sourceList.ts:264-272`).

## Rename / reword
15. **"All posts" means three things:** the rail's scope (excludes sources out of the main feed: 1,890 vs its parts 2,564 and 2,874; `repo_reader.py:246`), ⌘K's All filter, and Starred is both a rail entry and a Show choice. Name the scope "Main feed"; keep "All" only as the filter; one Starred.
16. "Digest" is retired (0005) but named in the sheet, track menu, bulk bar and toasts. One name: "Show in Main feed". The sheet's "readable through its tracks" is wrong for a source with no tracks.
17. Kind vs platform: the list says "Substack"/"Reddit", the sheet "RSS"; Group by Platform splits subreddits; the post header shows "/ rss". Use the kind everywhere; group by Kind.
18. Archive catalog shows UUIDs for URL-named sources (`IngestionArchive.tsx:229,258`); every Nitter source would be named "nitter.local" (`sourceLabel.ts:54`), likewise telegram.local. Derive names from the path.
19. Cadence: "probation" twice, and jargon (tier, backlog guard, kind floor, "Override (hours)"). E.g. "Fetched every 1 day (new source, until it has 3 dated posts). Set your own: __ hours."
20. "N in backlog" reads as unread posts; it means archivable older posts: "N older posts not archived".
21. "Hourly checks that find nothing due…" while the interval is configurable: "Scheduler checks…".
22. Smaller: "Priority" only orders sources inside one run and every source is 999 (and 0013 plans a different Priority): rename "Fetch order" or remove; the sources.json sync toggle doesn't warn that missing sources are deleted with their posts; the Sources header repeats the chip counts; the stream divider repeats the header and title; the sheet's Cancel sits beside settings that already saved; "Feeds" (mobile drawer) and "folders" (an error) where the app says sources and tracks.

Screenshots: `/tmp/audit-*.png` (local, temporary).
