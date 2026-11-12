# 0148 Built: track scout

Built 2026-11-12 on branch `scout-research` (Stealth v10.14), from main at d16336f. **Migration 0106**
(`mx_scout_runs`, `mx_scout_candidates`, `mx_scout_items`, `mx_source_provenance`; `mx_tasks.subject_kind` may be
`scout_item`). Mark X tables only, no key to a Mark IX table; the owner's Follow adds a source as POST /api/sources
adds one. Not measured on real data yet (see "Measure"); private rows go to `plan/research/0148-notes.md`.

realdata-check: run at release (not run here).

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | When a track scouts | `markx/scout.py`: `start` on the owner's tap (`POST /api/markx/tracks/{id}/scout`, the Topic view's **Find sources for this track**); `due_weekly`: a described track with fewer than 5 items in or ✓ in 7 days and no scout in 7 days, started by insight-ingestion's hook (`with_scouts`, after the story job's originals, in `ingestion.default_runner`). A folder without a description is not scouted (400). |
| 2.1 | Finder `match` | The link targets of the track's in and ✓ posts (newest 200), by Discover's address key (`discover_rules.discover_address`, the platforms Discover found); a code host's or model hub's thing keyed by its owner (`entity_originals.platform_thing`); never a followed site, account or source address, never a reference / app / archive / document / paper place (`place_kind`, `paper_address`), never a source's link to itself, never a key answered for this track before. Most linked first; the linked pages go to the finder as `linked` (it starts at their section). |
| 2.2 | Finder `shape` | `shape_candidates`: per platform class INSIGHT reads, from the track's words (0147's lexicon over the in items when 2+, else the description's words; the excludes' words left out) and the names 2+ in-items make their subject or actor: Reddit's search feed and the Hacker News class's search feed for the first two phrases, X's search through the configured bridge (only with one), a subreddit named by a word, a video channel and an X account (bridge only) named by a name. No site is named; the platform classes' own address shapes only. |
| 2.3 | Finder `haiku` | Kind `scout`, guide `scout-v1` (subject `track`, a = the folder), one a run: the description, the excludes, the platform classes INSIGHT reads, the track's active sources (not to name) and its 10 best items; answer `{sources: 5-30 of {platform (enum), address, name, why}}` (`schemas.SCOUT_SCHEMA`, `validate._scout`: one address without spaces, at most 300 characters, named once, `why` one line). The same question is one task (a second run reuses its answer, no second call). `after_answer` turns it into candidates (addresses normalised by platform class: `r/x`, `@h`, a bare host). |
| 3 | Test read | `markx/scout_reads.py` `Reader.read`: an account a source kind reads (X through the bridge, Telegram, a subreddit, a YouTube channel: `discover_reads.kind_source`) through that kind; anything else through `where_linked.follow` (the feed finder, then page watching): its first feed that is the page's own, else its first page to watch, read article by article as page watching reads them but never dated "now". Up to 20 newest items (8 for a YouTube channel: a video read is heavy) into `mx_scout_items`: never a post, nothing followed, nothing in a feed. Every request through the read's client is counted. With `INSIGHT_DISCOVER_READS=0` nothing is read. |
| 3 | Judge, precision, health | Each item read well is a `track` task (0145's `track-v1`, subject `scout_item`, a = the item, the track's own header), copied to the item when answered (`scout.after_judge`, from `tasks.record`); precision = in / judged. Health (`scout_reads.health`, 0135/0149's classes): no items, undated (under half dated), titles only (median text under 40 characters), stopped (newest over 120 days): "can't read well: <why>", never suggested; labels that don't stop it: summaries only (median under 400), its language, no transcripts. A candidate the finder can't read says the finder's reason. |
| 4 | Suggested | `scout.suggestions` / `page`: the newest read of each key of the track's scouts, not answered, read well, 5+ judged (or all its items), precision 30%+; ranked by precision, then cadence. `GET /api/markx/tracks/{id}/scout` (the Topic view's block; it advances a run with reads or judge questions due, in the background) and `GET /api/markx/scout/suggestions` (Discover's rows under each track's name). Follow: `POST /api/markx/scout/candidates/{id}/follow {as: active | passive}` adds the address the add path resolved at the test read (a feed, a watched page with its prefix, or a kind's handle) through `SourcesService.add_with_settings` and the sources.json export (an address already a source is that source); active also joins the track's folder. Not this one: `.../not`, never offered again for the track. Provenance: `mx_source_provenance` (source, scout run, candidate, track, active or not); the block lists each followed source with its precision in the track since. |
| 5 | Cost guard | Per run: at most 40 test reads (each finder's share first: match 15, haiku 15, shape 10, then refilled), 800 judgements, one `scout` call, 800 requests (the test reads' own budget; spent reads, requests and judgements in `mx_scout_runs` and `stats.spent`, and the log). A run is claimed (`busy_until`) by whoever advances it, so two never read it at once. The scout's judge tasks never count in the track planner's cap (`tracks.open_tasks` counts subject `post_track`). |

Frontend: `components/tracks/TrackScout.tsx` (the Topic view's **Sources for this track**, after Discover),
`components/tracks/ScoutSourceLines.tsx` (Discover's rows under the track's name, `pages/SourcesConfig.tsx`),
`services/scout.ts`. Design: `reader.md` (View topic: Sources for this track), `sources.md` (Discover's rows).
Worker: `scout` in `DEFAULT_KINDS` (before `track`), `PER_CALL scout=1`. Routes: `markx/scout_api.py`.

## Tests

- `test_markx_scout` (29, stubbed requests): the kind, guide, schema and validation; addresses by platform class;
  Haiku's answer as candidates; keys (a code host's owner, a subreddit, a search feed its own); the shapes with search
  feeds (X only through a bridge); the description's terms (the excludes left out); the health reasons and labels; a
  feed found by the finder read with the fetcher's parser (FakeHttp, the real registry and finder), an undated feed, a
  platform account through its kind, none found with its reason. On the test database: the weekly trigger (a quiet
  track, once a week, not with 5 in in 7 days) through the ingestion tick; the tap through the API with the background
  read; a folder is not scouted; finder 1 (most linked first, the owner key, a followed site, a reference place left
  out); the run's finders and the `scout` question, its answer as candidates (a key another finder had keeps it); the
  same question once; the test read into the scratch area (no source, no post, no folder change; 20 judge questions
  of subject `scout_item`, none in the track planner's cap); an unreadable candidate's reason and no judge; reads off
  with `INSIGHT_DISCOVER_READS=0`; ranked by precision with the 30% floor, the undated one under "reads badly", the
  Discover rows; follow active / passive through the add path (the resolved feed address), folder membership, the
  provenance rows, its later precision; Not this one never offered again; an unreadable one can't be followed; the cost
  guard (reads, judgements, requests, the finder shares, the claim).
- `test_markx_validate`, `test_markx_storage`, `test_markx_api` (MX_TABLES) updated for the kind and the tables.
- Worker: `scripts/tests/test_markx_worker.py` `TestScout` (fake-claude): a default kind before `track`, one a call.
- Frontend: `components/tracks/scout.test.tsx` (7): the lines in words, the block's rows, follow active / passive, not
  this one, the tap, Discover's rows and nothing while Mark X is off.

## Measure (to run on the server; not run here)

The scout reads with the server's fetcher, so these run on the server after deploy (Mark X on, the worker run by hand):

1. "Cool 3D Projects": open its Topic view, **Find sources for this track**. After the read (the block says
   "Waiting for Haiku…"), run the worker once (`scripts/markx-worker cycle --kinds scout,track` within a stated cap);
   the block reads the Haiku candidates on its next look (or the next ingestion tick), then run the worker again for
   the judgements. Count from `GET /api/markx/tracks/<id>/scout` → `runs[0].finders` (candidates, read, read well per
   finder), the suggested rows with precision ≥ 0.5, and the owner's follows. Rows: `plan/research/0148-notes.md`.
2. One sphere far from AI (the owner picks; e.g. 0135's health/psychology "Starting Point"): describe a track for it,
   the same steps and counts, and the `reason`s of the unreadable and "reads badly" rows (should be 0135/0137's
   classes, now said).
3. Per run: `runs[0].reads`, `requests`, `judgements` (and `stats.spent`), and the calls' cost from the worker's log.

## Open

- Hub listings ("a model or project hub's listing" in finder 2) are not built: a hub's listing address is not a class
  INSIGHT knows without naming the site; hubs come through finder 1 (owners the matches link) and Haiku. Add when a
  measured run shows the gap.
- The weekly scout runs from insight-ingestion's hook after a scheduled run that saved posts (not on a clock of its
  own); with the worker run by hand its Haiku candidates and judgements wait for the worker.
- Following re-uses the address the finder resolved at the test read (not a second finder run at the tap).
- A YouTube channel's test read keeps 8 videos, not 20 (each video's details and transcript are read).
