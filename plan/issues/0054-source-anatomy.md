# 0054 — Source anatomy: how each source is read, and what it gives

Status: **spec** (2026-10-30) for v9.6 (owner, 2026-10-30: "do we have a page … for the sources? I want to display how sources are built and what they build. So add them near the ingestion page.").

## The case
- **No page answers "how is this source read, and what does it give me?" for all sources at once.**
  - Sources → Ingestion shows the scheduler, the last run, the archive, jobs and logs.
  - A source's sheet shows its settings and health, one source at a time.
- **0050 and 0051 add new things a source gives:** stories it covered, stories it reported first, classics it cited, sites it points Discover to. These live nowhere per source.
- **On the server's data the gaps are real:**
  - 99 sources have no name of their own;
  - a quarter of Telegram and X sources never appear in a story;
  - HN takes articles from sites the owner follows (0017).
  - The owner can't see any of that today.

## Decided
- **Where:** a new view in Sources → Ingestion, `?sub=sources`, next to overview, archive, jobs and logs. One row per source. A click opens the source's existing sheet; no new editor.
- **How it's read** (from what INSIGHT already stores; nothing new is fetched):
  - **kind:** feed, page watching, site reader (Gwern), Telegram, X, Reddit, YouTube, Saved;
  - **address**, shown with the shared source-name helper;
  - **full text:** on, off, or the feed carries it;
  - **change watching:** on or off (0039);
  - **conditional fetching:** validators stored or not (0044);
  - **schedule:** its cadence and when it's due;
  - **last fetch:** when, and its last error if any.
- **What it gives** (over the last 30 days, with all-time on hover):
  - posts, and how many you read;
  - stories it's in, and how many it **reported first** (0050's lead);
  - classics it cited (0051);
  - outside links it gave (0050's post links).
- **Sorting:** by any column, as the sources list does (0011). The default order is the most posts.
- **Minimal:**
  - one query per column group, from tables that exist;
  - no new tables, unless a count is too slow (measure on the lab first);
  - no charts, no new settings.

## Done when
- **Backend:** one endpoint for the view, with tests on a `_test` DB covering each column. It answers in under 500 ms on the lab copy of the server's data (41k posts, 240 sources); measured, and recorded here.
- **Frontend:** tests for the view, its sorting, and opening a source's sheet. Screens in light and dark, wide and narrow.
- **Checks:** backend suite and frontend checks green; bundle within the 1% budget (lazy-load the view if needed).
