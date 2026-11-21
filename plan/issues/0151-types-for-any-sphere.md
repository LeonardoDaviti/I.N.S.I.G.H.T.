# 0151 — Types that fit any sphere: things and happenings named so that "other" is rare outside AI news

Status: **spec; E3 (2026-11-10) passed the list on five spheres of six and on AI news** (see "Measured"); one
addition and the candidate-pairs check remain. Fusion stage 2 (Read). Guides only; no new table. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: 0090 (entities), 0133 (ent-v4: documents and cited sources), 0127 / 0128 (read-v3's event type);
`markx/guides/ent-v3.md`, `read-v3.md`; `markx/candidates.py` (the `entity` source limits a candidate to types that
name one thing); `markx/identity.py`.

## Why (rough: private `plan/research/fusion/out/F1b`, `F1d`)
- Today's guides were written on AI and tech news. On posts of other spheres (health, economics, science, local
  news) **46% of entities and events fell into "other"**; on AI news itself, 24%.
- A list written without a sphere in mind left **2.4% "other" off-sphere and 1.8% on AI**, on unseen posts.
- The borders that blurred: study against document, tool against product.

## What it does
- **Things** (the entity guide's `type`): person, organisation, place, product, tool, model, document, study,
  dataset, event, law, concept, substance, condition, group, method, indicator; plus a free `kind` word when none
  fits ("other" stays, with the word).
- **Happenings** (the reading's `event_type`): announcement, study result, statement, deal, rule change, incident,
  personnel, unconfirmed claim, opinion, explainer.
- **Nothing downstream changes meaning:** a mapping table from the new types to today's is part of the guide's
  release, so identity keys, the candidate finder's "names one thing" set (model, product, software, paper, dataset
  today → model, product, tool, study, dataset, document, law), surges and the entity pages read old and new rows
  alike.
- Shipped as a guide version behind the existing guide switch (as ent-v4 was: default the current guide).

## Measure
E3 (0161): "other" under 10% on four spheres; on AI news, entity precision and the candidate finder's `entity`
pairs not below today's.

## What the results should be
- A reader of a non-AI sphere sees typed entities and event types on nearly every post.
- The owner's AI news reads no worse than today, row for row, on the lab's frozen sets.

## Done when
- The guide and the mapping; tests: every new type maps; old rows read unchanged.
- E3's report with exact rows (right, wrong, missed), private.

## Measured (E3, 2026-11-10; private: `plan/research/fusion/measure/E3/REPORT.md`)
180 unseen posts, 30 a sphere, read by the shipped ent-v4.2 and by the same guide with only the type list changed
(seven types added: study, substance, condition, indicator, object, group, method; `other` with a free `kind`).

| Sphere | "other", today's guide | "other", this list |
|---|---|---|
| AI news | 9.1% | 6.8% |
| Georgian news | 4.1% | 5.0% |
| Climate and energy | 13.4% | 5.7% |
| Health | 16.5% | 4.6% |
| Space | 24.6% | 10.3% |
| Football | 2.9% | 0.3% |

- Checked on 89 posts an arm (one Haiku checker): a named thing the post talks about 99.3% → 99.5%; type right
  95.0% → 95.5%; on AI news type right 93.2% → 95.9%. More entities found (1,435 → 1,605).
- **"Why" corrected:** the 46% and 24% above were measured with a guide that also listed unnamed things. With the
  shipped guide "other" is 3–25% by sphere; the gain is real but smaller.
- **The list in "What it does" is replaced by the measured one:** today's types plus the seven above. `tool` and `concept` are
  not added: `software` stays, and an unnamed concept is still no entity.
- **Not measured here:** the happenings list (the reading's event types). It keeps waiting for its own set.
- **Left:** a home for named programmes and missions (space's remaining `other`, and the type the checker most
  often disputed), on a new set; the candidate finder's `entity` pairs on the lab's frozen AI sets; the mapping for
  identity keys; a second checker.

## Measured again (types-v2, 2026-11-20; private: `plan/research/fusion/measure/x1120/T2/`)
New set, 180 posts, six spheres; "today" = the shipped ent-v5; neutral-v2 = the E3 list plus `programme`. Two checker passes.
| Sphere | other, ent-v5 | other, neutral-v2 |
|---|---|---|
| AI news | 3.7% | 1.8% |
| Georgian news | 5.8% | 1.2% |
| Climate and energy | 11.0% | 4.2% |
| Health | 8.0% | 7.2% |
| Space | 24.0% | 6.1% |
| Football | 2.7% | 2.1% |
- Under 10% in every sphere. Type right overall 96.0% -> 96.4%; named thing 99.7% -> 99.5%.
- **AI news: type right 97.3% -> 96.0% (overlapping intervals), so the "not below today's" condition is not met at the point.** Three of the nine AI errors are the new types (a rocket as `object`, beacon standards).
- Candidate-pair types on AI: 76 -> 93 entities; subjects 20 -> 16 (mostly run-to-run choice). `study` never appeared (untested). The type mapping table is in the report.
- Decision: ready for non-AI spheres; for the AI default, one guide sentence on products vs objects and a re-check.
