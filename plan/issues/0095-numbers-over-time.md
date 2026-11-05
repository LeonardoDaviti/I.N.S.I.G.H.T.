# 0095 — Numbers over time: prices, scores and money, per entity, with their sources

Status: **future** (2026-11-04). Mark X, after 0090 (entities).

## Why
- The readings already pull out each post's key numbers (`main.numbers`), but they're thrown away as text.
- Questions like these are among the most common in AI and tech news, and a feed can't answer them:
  - "What does Claude cost per million tokens now, and before?"
  - "Which models passed 80% on this benchmark, and when?"
  - "How much has this company raised?"

## What
- **One row per stated figure:**
  - entity (0090);
  - quantity: price in, price out, benchmark score (with the benchmark), funding, valuation, revenue, parameters, context window, users;
  - value and unit;
  - date;
  - the post and the exact span.
- **A table and a small chart per entity and quantity,** each point linked to its post.
- **Conflicting figures for the same thing and date** are shown side by side, never averaged.

## How
- **Extraction:** part of entity extraction (a `numbers` list, a separate guide version) or its own task. The checks are code:
  - the figure occurs in the post;
  - the entity occurs in the post;
  - the unit is from its set.
- **Every figure keeps its post:** a figure no post states is never shown.

## Measure before adopting
100 posts with figures, labelled: is each figure right, about the right entity, with the right unit and date? The bar is 95% precision.
