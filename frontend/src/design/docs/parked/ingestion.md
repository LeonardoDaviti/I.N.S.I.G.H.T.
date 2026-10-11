```meta
kind: parked
routes: /ingestion, /ingestion/:tab
```

# Ingestion page (old)

`pages/IngestionControl.tsx`. The full operations page: run a cycle, the run report, the scheduler, archive control and logs, under lowercase tabs. Reading-only its job moved to the **ingestion** tab under Sources (decision 005, `pages/sources.md`), so `/ingestion[/:tab]` redirects to `/settings/sources?tab=ingestion`, carrying the tab as `sub` and the query (P7, P9). Archive control and logs live there too now (issue 0005 slice 3). With analysis on, the old page still shows until issue 0005 deletes it (P10).
