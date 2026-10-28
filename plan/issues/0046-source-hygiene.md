# 0046 — Source hygiene: which sources went quiet, which you never read

Status: **planned** for v9.5 (owner, 2026-10-28).

## Why
Sources pile up. Some stop publishing, and some you never open. Neither shows today unless the source is broken (the doctor, 0036, covers broken).

## Decided
- **Two marks, computed from data INSIGHT already has:**
  - **Quiet:** fetches work, but nothing new has arrived for 30 days **and** for more than 3× the source's own usual gap between posts. A monthly newsletter isn't quiet at day 31. Shown as "Quiet: last post 4 Mar".
  - **Never opened:** at least 20 posts over at least 30 days since it was added, and none opened, saved to Later or kept. Shown as "Never opened: 214 posts".
  - Broken sources keep the doctor's notes and get neither mark.
- **Where:**
  - the Sources list shows the mark in its note column, where the doctor's notes already live;
  - a **"Tidy up"** view (a filter of the Sources list, not a new page) lists the marked sources, each with **Remove** and **Keep**.
  - **Keep** dismisses the mark for that source; it comes back only if it's still true 90 days later.
- **Never automatic:** nothing is removed or muted without the owner's click. Removing works exactly like removing a source today (sources.json included).
- **Backend:** the marks come with the health/list data the Sources page already loads, computed in SQL. Migration **0035** only if the dismissal needs storage.

## Done when
- Backend tests cover: quiet against the source's own cadence; never-opened counting opens, Later and Keep; broken sources excluded; dismissal and its 90-day return.
- Frontend tests cover the notes, the Tidy up filter, Remove and Keep.
- A dry run on a copy of the preview data (`insight_preview`, read only): how many sources get each mark, with a few examples, recorded here.
