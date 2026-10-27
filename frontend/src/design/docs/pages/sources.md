```meta
kind: page
routes: /settings/sources
states: dense, search-no-hits, bulk-selection, source-sheet, connections-set, connections-unset, connections-expired, ingestion-partial-failure, scheduler-stopped, ingestion-archive, ingestion-logs
```

# Sources

Code: `pages/SourcesConfig.tsx`, `components/sources/*`, `components/SourceSettingsEditor.tsx`, `components/connections/*`, `components/ops/*`.

## Purpose

Where sources are managed, and the only home of ingestion jobs and secrets (P7): add, group, tune, switch off or delete sources; see whether ingestion runs; set provider credentials.

## Entry & URL

- `/settings/sources`, from the `sources` nav word, ⌘K (Sources, Ingestion) and every source or track name in a reading view (P8).
- Tabs as `?tab=`: none = **sources**, `connections` (`&provider=<id>` opens that provider), `ingestion` (`&sub=archive|jobs|logs` for its views, `&job=<id>` for one job, `&sub=archive&source=<id>` for one source's backfill).
- Sources tab view in the URL: `?q=`, `?status=`, `?group=track|kind` (none, one flat list, is the default; the old `?group=platform` groups by kind), `?sort=name|kind|posts|lastPost|added` (status is the default) and `?dir=asc|desc` (left out while it is the column's own: name and kind ascending, the rest descending; status descending is worst first). The legacy `?tab=health` opens the flat list with its `?status=`; old or unknown values (`sort=success`, `group=status`) fall back to the defaults.
- `?source=<id>` opens that source's detail sheet; closing the sheet removes it, and Back closes the sheet. `?track=<id>` groups by track, scrolls to the track's group and briefly highlights it. An unknown id shows the list with a quiet note ("That source no longer exists"), no error page.
- `/ingestion[/:tab]` (the old ingestion page) redirects here, to the view that holds that tab, carrying the query. Dev-only `?data=worst|empty|one|huge`.

## Anatomy

- **PageHeader:** "Sources", a meta line (`90 sources · 6 tracks · as of 2m ago`; the chips count the enabled and failing ones), actions ghost "New track" and primary "+ Add source" (a dialog: templates, then the address; a template that always builds one address, like Pipecraft or Gwern, has no field, fills the address and says in one plain sentence what it adds, and is not offered once that source exists; Advanced holds only Fetch delay).
- **Tabs:** lowercase underline `sources / connections / ingestion`.
- **sources tab:** a toolbar (search field, status chips Enabled · Disabled · Failing (backoff included), then, only while they have sources, Unavailable · Due · Scheduled, each with a count; the Group select: No grouping · Track · Kind (the Kind column's names, so a subreddit groups with Reddit whatever its address); below md a "Sort: Added ↓" button that opens the column sort buttons as a row), then column headers that sort (Name, Kind, Posts, Last post, Added, Status: a press sorts, a second press reverses, the active one is pressed and shows ↑/↓), then one dense list. Flat by default; grouped, the groups have sticky, collapsible headers and, for a track, a ⋯ track menu (Fetch now on phones, Rename…, Show in Main feed, its check read from the track's sources: ✓ all in, – some, none blank; a press puts them all in or, when all are in, takes them out; Delete track…); the sources in no track come last, after a thin divider, without a header. A row, 36px: checkbox (revealed on hover/focus or once anything is selected), status glyph, name (opens the sheet), kind, posts, last new post, added, a status note, a read arrow (opens the reader on the source; revealed on hover/focus, always on touch), on/off switch. On a phone: glyph, name, posts, read, switch; never a URL.
- **Bulk bar** (sticky bottom, while rows are selected): count, on/off, Add to track, Remove from track, Show in Main feed (on or off), Delete, clear (Esc).
- **Source sheet** (from the right, 32rem): name, its kind (as the Kind column names it) and "Read posts", the address with copy, a health summary (a due source reads `due · next check in 37m`, the scheduler's next tick, or `due · scheduler not running`), "Fetch now" (optional; it ignores cadence and backoff; "Fetching…" while any fetch or archive job of the source runs, also one started before the sheet opened) and the on/off switch, then Name, Tracks, Show in Main feed (off keeps it fetched and readable on its own page), how often it is fetched and why in plain words ("Fetched every 1d (new source, until it has 3 dated posts)") with "Set your own (hours)", Fetch delay; Save (for Name and Fetch delay; the rest saves instantly, so there is no Cancel: the sheet closes with × or Esc); Delete. How many posts one fetch reads and the order sources are fetched in are INSIGHT's own per kind, not settings. Below them, **Archive**: Stored and At the source (worded by what the source can tell, with `measured 3d ago` or `not measured yet`), then Plan, which measures the source and says where the archive continues from and how much is older ("You have 120 posts, back to 3 Mar 2025. The archive continues from there: about 2,180 older posts · ~18m", or "… · size unknown" when the source reports no size); an archive fetches everything older than what is stored, jumping below the oldest stored post when the source allows it, so there is no count to choose. Run or Resume archive with a progress bar while it runs, then the last run's result; an archive a site paused by limiting us shows a warning notice, "Paused: reddit.com is limiting us", with Resume (it continues from the checkpoint); a source that cannot archive is one quiet line (a subreddit: "Reddit refuses archive requests for now"). A second archive of a source is refused while its first one runs. A source that is off or unavailable has no Fetch now, main feed, cadence or archive: one line says why ("Off: not fetched until you switch it on", or the reason it is unavailable with "add in Connections").
- **connections tab:** one row per provider with something to add (Substack, Telegram; Reddit and YouTube read public feeds and have no row) with glyph + word (`working`, `set · not tested`, `failing`, `incomplete`, `sign in needed`, `not set`); a row opens to its write-only fields (a set field shows `set · ••••a3f · updated <date>`, never the value), a Test button, Telegram sign-in, Substack how-to.
- **ingestion tab:** sub-nav `overview / archive / jobs / logs`. Overview: Scheduler (how often it checks, next tick, "Change interval"; its dialog's "Sync sources.json every cycle" warns that a source missing from the file is deleted with its posts), "Run due sources", Last run. A run report says what the run delivered, in words ("34 new posts from 5 sources", "Nothing new: 12 sources checked", "Nothing was due", "3 sources failed"), then the sources that delivered, each with its count and a link to read it, and the failed sources, one line each with the reason; no zero counts, no raw JSON. The scheduler wakes every `ingest_tick_minutes` (60) and fetches only the sources whose own cadence is due; a tick with nothing due is a cheap check with no request, so it leaves no job (the Scheduler line still shows the ticks). Archive: the catalog of enabled sources that can archive (a feed that lists no more posts than one fetch reads, and a kind this server cannot fetch, are left out; one fetch reads what the kind's fetches read, 20 for a feed) (glyph + word `archived` / `partial` / `not archived`, stored of available, `1,602 older posts not archived` (or `nothing older to archive`), `measured 3d ago` or `not measured yet`, a saved checkpoint), searchable; the picked source gets the sheet's archive controls plus Pacing (page delay, batch size, batch cooldown; blank keeps the source's own value), and the run shows in jobs. Jobs: the job history, each run worded by what it delivered; a job opens its report and its events, one line per source fetched ("r/viture: 3 new of 25 · 52 of 81 sources") and per slow-down. Logs: one backend log's last 200 lines, a log picker and Refresh; it refreshes every 30 seconds. Under every view, one quiet `text-fg-3` line with the running version (P11): `I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026`; when the web app and the API differ, both and "out of step"; unstamped, `dev build`.

## States

- **dense:** 90+ sources in the flat list, a few failing and in backoff.
- **search-no-hits:** "No sources match" with "Clear filters".
- **bulk-selection:** several rows checked, the bulk bar showing.
- **source-sheet:** the sheet open on a source (`?source=<id>`).
- **connections-set / connections-unset / connections-expired:** providers working; nothing set; a failing test or a lapsed session ("sign in needed").
- **ingestion-partial-failure:** the last run report with some sources failed, each with its message.
- **scheduler-stopped:** the scheduler has not ticked: one clear warning line (P11).
- **ingestion-archive:** the catalog with a channel picked for a backfill, its checkpoint ready to resume.
- **ingestion-logs:** the application log's tail.
- Also: no sources yet ("No sources yet" + Add source), loading (eight-row skeleton), load error (`ErrorState` with Retry), a failed refresh with the last loaded list kept (warning `Notice` + Retry).

## Interactions & keys

- `j`/`k` move the active row, `x` select, `o`/Enter open the sheet, Esc clear the selection. Never inside a field, dialog or menu; single keys follow the reader's shortcut switch. Shift-click selects a range.
- Adding a source fetches it straight away (an enabled one): its toast goes from "Added — fetching now" to the run's result, so nobody waits for the scheduler.
- Deleting a source or a track asks first and says what goes with it (`ConfirmDialog`). New track and Rename are small dialogs.
- Switching tabs closes the sheet; a link out of the sheet ("add in Connections") switches tab.

## Worst cases

- Long or URL-only names middle-truncate with the full name in `title`; derived names via `sourceLabel()`.
- Counts and dates are tabular and never truncate; columns drop by width (the headers, kind and last post below sm; added and status below md, where the toolbar's "Sort:" button reaches every column's sort).
- A failing message of several hundred characters wraps in the sheet; in the run report it is one line, the full text in `title`.
- Hundreds of sources: groups collapse; headers stay sticky under the toolbar.

## A11y & motion

- Roving focus: only the active row's controls are tab stops. The column headers are buttons with a pressed state, named with their direction (`Sort by Posts, descending`), not `aria-sort`: the list is not a table. Status is glyph + word everywhere. Checkboxes and switches carry labels; the track menu is a `menu` with `menuitem`s.
- Tabs never animate; the sheet slides 260ms in / 200ms out and fades under reduced motion; dialogs scale from 0.97 (P12).

## Decisions

- 005 ingestion is a tab here, 008 secrets only in Connections, 011 names in reading views link here (`../decisions.md`).

## Open issues

- [0003](../../../../../plan/issues/0003-source-name-opens-source-settings.md): the `?source=` / `?track=` deep links.
- [0005](../../../../../plan/issues/0005-minimal-codebase.md): keep what reading uses, retire the rest.
- [0011](../../../../../plan/issues/0011-sources-list-sort-and-read.md): sort by column, the Added column, flat by default, read from a row.
