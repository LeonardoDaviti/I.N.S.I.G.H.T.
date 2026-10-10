```meta
kind: system
redirects: /hub, /tracks/:trackId, *
```

# Information architecture

Implements P1, P7, P9 and P10. Source: `src/App.tsx`, `components/layout/navigation.ts`.

INSIGHT is reading-only by default (`INSIGHT_ANALYSIS` off): three places, **feed / sources / post**.

```
┌──────────────────────────────────────────────────────────────┐
│ [INSIGHT]                              feed / sources  [go to ⌘K] ☾ │
└──────────────────────────────────────────────────────────────┘
```

| Nav word | Route | Active on |
| --- | --- | --- |
| feed | `/` | `/`, `/read/*`, `/posts/*` (and `/tracks*` reading-only) |
| sources | `/settings/sources` | `/settings/*` |

With analysis on, the bar is `feed / tracks / briefings / sources / ingestion`:

| Nav word | Route | Active on |
| --- | --- | --- |
| tracks | `/tracks` (tracks & experts) | `/tracks*`, `/experts` |
| briefings | `/briefing` | `/briefing*`, `/stories`, `/inbox` |
| ingestion | `/ingestion` | `/ingestion*` |

## Where each route lives

| Route | Doc |
| --- | --- |
| `/`, `/read/:scopeKind/:scopeId?` | `pages/reader.md` |
| `/posts/:postId` | `pages/post.md` |
| `/settings/sources` (tabs sources · connections · ingestion) | `pages/sources.md` |
| `/briefing`, `/briefing/topics` | `parked/briefing.md` |
| `/briefing/vertical`, `/briefing/vertical/source/:sourceId` | `parked/vertical-briefing.md` |
| `/stories` | `parked/stories.md` |
| `/inbox` | `parked/inbox.md` |
| `/tracks`, `/experts` | `parked/experts-tracks.md` |
| `/ingestion`, `/ingestion/:tab` | `parked/ingestion.md` |

**Redirects** (claimed in this doc's meta block):
- `/hub` → `/` (the Mark VIII hub is deleted, P1).
- `/tracks/:trackId` → `/read/folder/:trackId`, replacing the history entry (the track page is retired into the reader, P9).
- `*` (any unknown path) → `/`.

Parked routes redirect to `/` while analysis is off (P10), after `GET /api/config` settles so a deep link isn't bounced early. The flag is the backend's `INSIGHT_ANALYSIS` (default off) read from `GET /api/config`, falling back to the build flag `VITE_INSIGHT_ANALYSIS`; on, every parked surface comes back unchanged and the post page regains its analysis (`parked/post-analysis.md`). `/ingestion[/:tab]` goes to `/settings/sources?tab=ingestion` instead, carrying the tab and query.

## Cross-links (P8)

- A source name in a reading view links to `/settings/sources?source=<id>` (the source sheet opens).
- A track name links to `/settings/sources?track=<id>` (the list scrolls to the group and highlights it).
- Secrets have one home: `/settings/sources?tab=connections[&provider=<id>]` (P7).

## ⌘K quick switcher

Navigation only, it never searches posts. Reading-only it lists Unread, Starred, All posts, By source, one entry per track (to `/read/folder/:id`), Sources, Source health, Ingestion (the sources tab) and the theme toggle. With analysis on it lists the analysis destinations instead of the per-track entries. Below `sm` (640px) the nav words collapse into a `menu` button that opens the same switcher. Details: `pages/shell.md`.
