```meta
kind: parked
routes:
```

# Track briefing and milestones

`components/TrackBriefingPanel.tsx`, `components/MilestonesRail.tsx`. With analysis on, the reader scoped to a track (`/read/folder/<id>`) shows the latest *stored* briefing of the expert bound to that track (a dated issue header, the briefing in the reading measure, numbered topics, past issues as a date strip) and the milestones rail (landmark releases per vendor, a filled dot when several sources agree, a ring when one does). It never triggers generation, so opening a track costs no tokens. It has no route of its own since the track page was retired into the reader (decision 010, P9), and is hidden reading-only (P10). What should change in it is the owner's feedback in [0002](../../../../../plan/issues/0002-track-briefing-reading.md); the milestones idea is [0001](../../../../../plan/issues/0001-entity-pages-and-milestones.md).
