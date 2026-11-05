# 0097 — Where sources disagree: who supports, disputes or adds what, on one story

Status: **future** (2026-11-04). Mark X, medium–hard; after Shadow (0086).

## What
- **On a story with 3+ voices:** the claims its sources make, grouped, each with who supports it, who disputes it and who adds something new. For example: "3 sources say the model leads the benchmark; 1 says the comparison used an older version".
- **On the post page:** "this post disputes what 2 of your sources say".

## How
1. Extract the claims per member: one short claim per sentence of substance, with its exact span.
2. Group the claims within the story: the same claim in other words.
3. Judge the stance for each source and claim: supports, disputes, adds, neutral.
4. Show the groups that have a dispute or an addition first.

Haiku does steps 1 and 3; step 2 uses embeddings plus the judge. Every claim keeps its span.

## Measure before building further
50 multi-source stories, labelled: are the claims right, the groups right and the stances right? Show it only if the disputes it finds are real 90% of the time.
