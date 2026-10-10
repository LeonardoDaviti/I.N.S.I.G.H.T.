```meta
kind: parked
routes: /ingestion, /ingestion/:tab
```

# Ingestion page (old)

`pages/IngestionControl.tsx`. The full operations page: run a cycle, the run report, the scheduler, archive control and logs, under lowercase tabs. Reading-only its job moved to the **ingestion** tab under Sources (decision 005, `pages/sources.md`), so `/ingestion[/:tab]` redirects to `/settings/sources?tab=ingestion`, carrying the tab and query (P7, P9). With analysis on, the page comes back unchanged with archive control and logs, which the tab does not have (P10).
