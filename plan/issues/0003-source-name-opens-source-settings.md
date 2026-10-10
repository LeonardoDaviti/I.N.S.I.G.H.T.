# 0003 — Clicking a source or track name opens it in Sources

Status: **open** (owner, 2026-10-10). Small UX fix.

## Problem
- **Reader:** on `/read/source/:id` (and `/read/folder/:id`), the source or track name in the header is plain text (`FeedToolbar`'s `<h1>`). You can't get from what you're reading to that source's settings, e.g. to remove it, without going to Sources and searching for it.
- **Sources page:** it has no deep link to a source. The detail sheet is opened by local state only (`SourcesConfig.tsx` `openId`), not by the URL.

## Wanted
- **Source header:** the source name in the reader header is a quiet link to `/settings/sources?source=<id>`. Sources opens with that source's **detail sheet open**, where you can change settings, disable or delete it.
- **Track header:** the track name links to `/settings/sources?track=<id>`. The list scrolls to that track's group and briefly highlights it; the group's ⋯ menu holds rename, main digest and delete.
- **Post page:** the source name in the byline links to the same place.
- **The URL owns the sheet:** opening the sheet sets `?source=`, closing it removes the parameter, and the back button closes the sheet.
- **Unknown or deleted id:** show the sources list with a quiet note, "That source no longer exists". No error page. (The id from the report, `a984b1ff-…`, is no longer in the preview database, so this case is real.)

## Principles
- Reading views never *do* ingestion work.
- Reading views are always one click from where the source is managed.
