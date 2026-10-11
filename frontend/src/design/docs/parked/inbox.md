```meta
kind: parked
routes: /inbox
```

# Analyst inbox

`pages/AnalystInboxPage.tsx`, sample data in `AnalystInboxPage.fixtures.ts`. Triage of generated candidates: a ranked list on the left (the batch is a filter like the others), the selected candidate on the right with its scores, reasons, the triage actions and the action history. Parked because it reviews model output, which reading-only does not produce (P10); off, `/inbox` redirects to `/`. Kept for the master/detail shape it shares with Stories, so both read the same way (P9).
