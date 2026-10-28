```meta
kind: system
redirects: /hub, /tracks/:trackId, /ingestion, /ingestion/:tab, /briefing, /briefing/topics, /briefing/vertical/*, /stories, /inbox, /experts, /tracks, *
```

# Information architecture

Implements P1, P7, P9 and P10. Source: `src/App.tsx`, `components/layout/navigation.ts`.

INSIGHT is a reader: three places, **feed / sources / post**, plus the **blog**.

```
┌──────────────────────────────────────────────────────────────┐
│ [INSIGHT]                       feed / sources / blog  [go to ⌘K] ☾ │
└──────────────────────────────────────────────────────────────┘
```

| Nav word | Route | Active on |
| --- | --- | --- |
| feed | `/` | `/`, `/read/*`, `/posts/*`, `/tracks/*`, `/search` |
| sources | `/settings/sources` | `/settings/*` |
| blog | `/blog` | `/blog*` |

## Where each route lives

| Route | Doc |
| --- | --- |
| `/`, `/read/:scopeKind/:scopeId?`, `/search` (search every post, issue 0040) | `pages/reader.md` |
| `/posts/:postId` | `pages/post.md` |
| `/settings/sources` (tabs sources · connections · ingestion) | `pages/sources.md` |
| `/blog`, `/blog/:slug` | `pages/blog.md` |
| `/design/*` (the Design Studio, described in `system/studio.md`) | `pages/shell.md` |
| `/save` (save any page: the bookmarklet and ⌘K, issue 0031) | `pages/shell.md` |

**Redirects** (claimed in this doc's meta block):
- `/hub` → `/` (the Mark VIII hub is deleted, P1).
- `/tracks/:trackId` → `/read/folder/:trackId`, replacing the history entry (the track page is retired into the reader, P9).
- `/ingestion`, `/ingestion/:tab` → `/settings/sources?tab=ingestion`, the old page's tab carried as `sub` and the rest of the query kept, replacing the history entry (the old ingestion page is deleted, `pages/sources.md`).
- `/briefing`, `/briefing/topics`, `/briefing/vertical/*`, `/stories`, `/inbox`, `/experts`, `/tracks` → `/`, replacing the history entry. These were the analysis pages, retired with analysis (decision 016, P10); old bookmarks land on the feed.
- `*` (any unknown path) → `/`.

## Cross-links (P8)

- A source name in a reading view links to `/settings/sources?source=<id>` (the source sheet opens). In a post's byline the source name reads the source (`/read/source/<id>`) and ` / settings` beside it opens the sheet (decision 020).
- A track name links to `/settings/sources?track=<id>` (the list scrolls to the group and highlights it).
- Secrets have one home: `/settings/sources?tab=connections[&provider=<id>]` (P7).

## ⌘K quick switcher

The places to go, then "Search posts…", which opens `/search` on what was typed (issue 0040); the studio is in no nav word, only here. Its entries, keys and the narrow `menu` button: `pages/shell.md`.
