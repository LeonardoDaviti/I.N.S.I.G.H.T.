# 0099 — Predictions checked later: what sources said would happen, checked when the date comes

Status: **future** (2026-11-04). Mark X, complex; after 0090 and 0091.

## What
- **Prediction posts:** posts that predict something datable ("X will release Y by June", "this approach will fail within a year") are kept with their due date and their entities.
- **When the date comes,** later posts are checked: happened, didn't happen, or unclear, with citations.
- **A source's track record:** predictions made, checked and right. Shown on the source page (with 0093) and in the weekly digest (0096).

## How
- **Detection:** a `prediction` field in the reading, holding the claim, the due date (stated or implied) and the entities.
- **Checking:** a scheduled task at the due date, with retrieval over the posts since (0098's machinery). Haiku judges, and every verdict keeps its evidence.

## Measure before adopting
- Detection precision on 100 posts.
- The verdicts on the first 30 due predictions, labelled by you.
