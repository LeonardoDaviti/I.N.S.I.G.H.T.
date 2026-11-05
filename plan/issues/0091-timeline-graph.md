# 0091 — The timeline graph: events, entities and their connections across time

Status: **discussion** (2026-11-04). Mark X, after Shadow's part E (0086) and entity identity (0090 C). Connections, the layers and the measured numbers are here; storage is 0086's.

## Why (the owner, 2026-11-04)
"Timeline-based graphs, which cover all the news, all the events, all the reasoning over everything we receive, and we can look at everything at any time, see connections and reason over news; not just consume readings and spend time on nonsense, but actually learn and become better."

So the graph is for understanding over time, not a bigger feed. Every connection keeps its evidence and its confidence, and an uncertain one is shown as uncertain.

## The layers, and where each stands

| Layer | What it holds | Where it stands |
|---|---|---|
| Posts and their links | every post with its time; links, citations, quotes, threads | built (Mark IX); the windows measured 2026-11-04 (0086) |
| What each post says | the event: who, what, version, date, numbers | measured: kind 86.7%, events 90.4% (Shadow reads every post) |
| Events (stories) | posts reporting the same event | measured: 98% right at the 0.6 bar; Shadow |
| Entities | companies, products with versions, people, with roles | 0090 (extraction v2 measured; identity next) |
| Development between events (≤ 30 days) | follows up, development, reaction | F6: "development" 13 of 15 right, same event 7 of 7, recall 95%; in Shadow |
| Connections across years | builds on, refers back, same topic | experiment G (below) |
| Trends | an entity surging against its own past | 57% real, 66% after a 7-day warm-up; fixed by counting main subjects per exact version (0090) |
| Claims over time | what a company said before and now | not started |
| Who broke it, sources of truth | first reporter, citation authority | the tree (0064) and Classics (0051); authority across the graph not started (0004) |
| Reasoning | briefings and answers with citations | briefing in Shadow; questions 0098 |

## Measured: connections across years (experiment G, 180 pairs, two blind labellers)
- **Plain nearest older posts aren't enough.** 19% of the most similar older posts (30+ days back, cosine ≥ 0.55) are meaningful connections; 77% at cosine ≥ 0.75.
- **Age matters:** 39% at 30–90 days, 7% at 6–12 months, none past a year (only 16 such pairs: the archive is thin; see 0102).
- **By relation:** "builds on" is right 10 of 12 (83%), but "follows up" only 16 of 32 (50%), because the next version of a product reads as a follow-up.
- **So:**
  - candidates come from high similarity, recent months, shared main entities (0090) and citations, not similarity alone;
  - a new version is an entity relation (`next_version`), not a follow-up of a story;
  - "follows up" is kept for the same event's continuation.

## The model
- **Nodes:**
  - posts;
  - stories (events);
  - entities (0090);
  - later, claims.
- **Edges**, each with a time, evidence (posts, the judge's words, or the rule), a confidence, and validity (`valid_from`, `valid_to`):
  - in a story: member, mention or digest item;
  - between events: same_event, development, follows_up, reaction;
  - across time: builds_on, refers_back, same_topic;
  - between a post and an entity: subject, actor, compared, predecessor, venue, mention;
  - between entities: released, acquired, invested_in, partnered_with, hired, joined, left, leads, based_on, beats, part_of, next_version.
- **As of a date:** every edge has its validity, so "what did I know on 1 March" is a query, not a reconstruction.
- **Storage:** 0086's `mx_connections` and `mx_mentions`, recursive queries for chains. No graph database: a million edges is small for Postgres.

## The views
- **Today:** News and the briefing (Shadow).
- **Timeline:** an entity or a topic over time: releases, papers, incidents, numbers (0090 F, 0095).
- **Chain:** what led to an event and what followed, each link typed and explained.
- **Ask:** questions across everything you've received (0098).
- **Study pages** compose them (0100).

## Measure before building
- **G2:** 200 cross-time candidates from the new candidate rule (similarity ≥ 0.75, shared main entity, citation), labelled by relation, against plain similarity.
- **"follows up" vs "next_version":** relabel G's 32 follow-up calls under the tightened definitions.
- **Chains:** 20 chains of 3+ events, judged whole by the owner.

## Done when
A story page shows its chain (what it follows and what followed) with typed, explained links, and an entity page shows its timeline (0090 F).
