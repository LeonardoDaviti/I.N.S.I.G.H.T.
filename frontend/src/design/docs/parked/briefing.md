```meta
kind: parked
routes: /briefing, /briefing/topics
```

# Briefing (daily / topics)

`pages/DailyBriefing.tsx`. A newsletter-style issue for a day: a dated header with the system line, one tab per briefing kind (daily / topics / weekly, plus the vertical page), one primary action per tab, then the issue text in the reading measure, a numbered topic list and the cited posts; it opens on the latest day that has posts. Parked because it is model-written analysis, hidden while `INSIGHT_ANALYSIS=off` (P10); off, both routes redirect to `/`. The owner liked reading a day as one issue in the news.smol.ai shape, and asked that it never open on an empty "0 posts" today and that its verbs collapse into tabs plus one action (P1, P11).
