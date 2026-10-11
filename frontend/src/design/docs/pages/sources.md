```meta
kind: page
routes: /settings/sources
states: dense, search-no-hits, bulk-selection, source-sheet, connections-set, connections-unset, connections-expired, ingestion-partial-failure, scheduler-stopped
```

# Sources

Code: `pages/SourcesConfig.tsx`, `components/sources/*`, `components/SourceSettingsEditor.tsx`, `components/connections/*`, `components/ops/*`.

## Purpose

Where sources are managed, and the only home of ingestion jobs and secrets (P7): add, group, tune, switch off or delete sources; see whether ingestion runs; set provider credentials.

## Entry & URL

- `/settings/sources`, from the `sources` nav word, ⌘K (Sources, Source health, Ingestion) and every source or track name in a reading view (P8).
- Tabs as `?tab=`: none = **sources**, `connections` (`&provider=<id>` opens that provider), `ingestion` (`&sub=jobs` for the job list, `&job=<id>` for one job).
- Sources tab view in the URL: `?q=`, `?status=`, `?group=status|platform|none` (track is the default), `?sort=name|success|posts` (status is the default). The legacy `?tab=health` opens the list grouped by status.
- `?source=<id>` opens that source's detail sheet; closing the sheet removes it, and Back closes the sheet. `?track=<id>` scrolls to the track's group and briefly highlights it. An unknown id shows the list with a quiet note ("That source no longer exists"), no error page.
- `/ingestion[/:tab]` redirects here reading-only. Dev-only `?data=worst|empty|one|huge`.

## Anatomy

- **PageHeader:** "Sources", a meta line (`90 sources · 84 on · 3 failing · 6 tracks · as of 2m ago`), actions ghost "New track" and primary "+ Add source".
- **Tabs:** lowercase underline `sources / connections / ingestion`.
- **sources tab:** a toolbar (search field, status chips Enabled · Disabled · Failing · Unavailable, then secondary Backoff · Due · Scheduled, each with a count; Group and Sort selects), then one dense list: groups with sticky, collapsible headers ("Not in a track" last) and a ⋯ track menu (Fetch now on phones, Rename…, In main feed and digest, Delete track…). A row, 36px: checkbox (revealed on hover/focus or once anything is selected), status glyph, name (opens the sheet), kind, posts, last new post, a status note, on/off switch. On a phone: glyph, name, posts, switch; never a URL.
- **Bulk bar** (sticky bottom, while rows are selected): count, on/off, Add to track, Remove from track, Main digest, Delete, clear (Esc).
- **Source sheet** (from the right, 32rem): name and platform, the address with copy, a health summary, "Fetch now" (ignores cadence and backoff) and the on/off switch, then Name, Tracks, In the main feed and digest, cadence override, Fetch delay, Priority, Max posts per fetch; Save; Delete. Below them, **Archive**: Stored and At the source (worded by what the source can tell), Posts to fetch with presets up to all of it, the plan (pages, time), Run or Resume archive with a progress bar while it runs, then the last run's result; a source that cannot archive is one quiet line. A second archive of a source is refused while its first one runs.
- **connections tab:** one row per provider with glyph + word (`working`, `set · not tested`, `failing`, `incomplete`, `sign in needed`, `not set`, `not needed`); a row opens to its write-only fields (a set field shows `set · ••••a3f · updated <date>`, never the value), a Test button, Telegram sign-in, Substack how-to. Analysis-only providers (Gemini, Langfuse) show only with analysis on.
- **ingestion tab:** sub-nav `overview / jobs`. Overview: Scheduler (how often it checks, next tick, "Change interval"), "Run due sources", Last run (fetched, inserted, failed, per-source failures; "Enrichment skipped (analysis off)"), raw payloads behind a closed disclosure. Jobs: the job history; a job opens its report and events. With analysis on: "Write a briefing" and the `sources.json` ↔ database registry buttons.

## States

- **dense:** 90+ sources grouped by track, a few failing and in backoff.
- **search-no-hits:** "No sources match" with "Clear filters".
- **bulk-selection:** several rows checked, the bulk bar showing.
- **source-sheet:** the sheet open on a source (`?source=<id>`).
- **connections-set / connections-unset / connections-expired:** providers working; nothing set; a failing test or a lapsed session ("sign in needed").
- **ingestion-partial-failure:** the last run report with some sources failed, each with its message.
- **scheduler-stopped:** the scheduler has not ticked: one clear warning line (P11).
- Also: no sources yet ("No sources yet" + Add source), loading (eight-row skeleton), load error (`ErrorState` with Retry), a failed refresh with the last loaded list kept (warning `Notice` + Retry).

## Interactions & keys

- `j`/`k` move the active row, `x` select, `o`/Enter open the sheet, Esc clear the selection. Never inside a field, dialog or menu; single keys follow the reader's shortcut switch. Shift-click selects a range.
- Deleting a source or a track asks first and says what goes with it (`ConfirmDialog`). New track and Rename are small dialogs.
- Switching tabs closes the sheet; a link out of the sheet ("add in Connections") switches tab.

## Worst cases

- Long or URL-only names middle-truncate with the full name in `title`; derived names via `sourceLabel()`.
- Counts and dates are tabular and never truncate; columns drop by width (kind and last post below sm, note below md).
- A failing message of several hundred characters wraps in the sheet and the run report.
- Hundreds of sources: groups collapse; headers stay sticky under the toolbar.

## A11y & motion

- Roving focus: only the active row's controls are tab stops. Status is glyph + word everywhere. Checkboxes and switches carry labels; the track menu is a `menu` with `menuitem`s.
- Tabs never animate; the sheet slides 260ms in / 200ms out and fades under reduced motion; dialogs scale from 0.97 (P12).

## Decisions

- 005 ingestion is a tab here, 008 secrets only in Connections, 011 names in reading views link here (`../decisions.md`).

## Open issues

- [0003](../../../../../plan/issues/0003-source-name-opens-source-settings.md): the `?source=` / `?track=` deep links.
- [0005](../../../../../plan/issues/0005-minimal-codebase.md): keep what reading uses, retire the rest.
