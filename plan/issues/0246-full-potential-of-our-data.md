# 0246 — The full potential of our data: what we store, what we use, what to develop

Status: **documentation / roadmap** (owner 2026-11-20: "cover all those potentials written in the issues, we need to
have documentation about what to develop"). Nothing here is built by this file. Row counts are the server export of
2026-11-19 (manifest.json); sizes from 0244.

Each asset below lists what it is, what reads it today, what it could give, and which issue owns that (an existing
issue where there is one; new numbers where not). The order at the end is my recommendation.

## The assets

| # | Asset (table) | Rows | Size | Read today by | Unused potential |
|---|---|---|---|---|---|
| A | Posts (`posts`) | 162,446 | 3.8 GB | the reader, everything | — (the base) |
| B | Links between posts and pages (`post_links`, `post_refs`) | 952,809 / 1,393,037 | ~0.5 GB | stories, Discover, originals | who reported first, a source's lead time, quote chains |
| C | Haiku questions and answers (`mx_tasks`, `mx_calls`) | 1,904,385 / 1,562,333 | 3.8 GB / 0.9 GB | the worker, every Mark X feature | answers kept but read by one feature each; inputs pruned by v10.25 |
| D | Readings: ent-v5's reading of each post (`mx_readings`, `mx_mentions`, `mx_units`) | 1,983,138 mentions, 638,383 units | ~0.8 GB | entities, stories, the graph | numbers, claims, predecessors, quotes: read for entities only |
| E | Entities and their vectors (`mx_entities`, `mx_entity_vectors`, `mx_entity_facts`) | 359,368 / 359,081 / 43 | 1.9 GB | entity pages, linking | "similar things", facts (43 rows only), briefing joins |
| F | Post embeddings (`mx_embeddings`) | 162,263 | ~0.5 GB | stories, sub-topics | search by meaning (0247, skipped for now), "more like this" |
| G | Connections (`mx_connections`: chains, relations, next versions) | 185,687 | — | the one-release row (v10.25), relations (on 2026-11-20) | earlier/later on a story, a thing's history, the timeline graph |
| H | Track judgments (`mx_track_items` and friends) | 164,440 | — | in/out, sub-topics, Discover lane | track briefings (0245), source fit per track, the "why" lines as summaries |
| I | Perspectives and story sheets (`mx_perspectives`, `mx_sheets`) | 10,236 / 861 | — | the story sheet | what each source adds (0157), where sources disagree (0097) |
| J | Mark X News rows (`mx_news`) | 145,986 | — | News | back in the news (0092/0136), weekly what changed (0096), surges (0159) |
| K | Your reading (`post_interactions`, `post_reader_state`, `mx_track_seen`) | 1,586 / 358 / 3 | small | unread state, Discover's reader fit (off) | ranking by what you read, "since you looked" (0154), source value (0158) |
| L | Discover and official channels (`discover_addresses`, `mx_source_judgements`, `mx_official_channels`) | — / 257 / 524 | ~17 MB | Discover, official (shadow) | a source's track record (0118), noise per source (0093) |

K is the thinnest: 358 read states and 1,586 opens. Anything ranked "by what you read" needs more reading inside
INSIGHT first, or it learns from almost nothing.

## The potentials, by what the reader gets

### 1. Things and briefings (H, D, E): **0245 track briefings** (planned for v10.27)
The track's own things (setups, projects, prints) pulled out of posts, the quick look, the weekly issue, tables.

### 2. A story's past and future (G, B): **0125 connected earlier/later/outside**, **0091 timeline graph**
- Chains are stored for every story pair about one thing (0219), and the reader sees none (`chains.shown: []`); only
  the one-release row uses `same_release`.
- Want: on a story, "earlier" and "later" (the leak before, the AMA after, the next version), each with its relation.
- Bar: the other chain relations were 33-75% on held-out sets (0219): they need a better guide, or the owner's switch.

### 3. Who said what, first and differently (B, I, D): **0157 what a post adds**, **0158 what a source adds**, **0097 where sources disagree**
- `post_refs` and links already say who linked whom; perspectives say what each member adds.
- Want: per story, who reported it first (and how much earlier than your other sources), what each source adds, and
  where two sources state different facts.
- Per source: its lead time, its share of firsts, what it adds that no one else does (a source's value, 0158).

### 4. Numbers and claims over time (D): **0095 numbers over time**, **0152 claims at read time**, **0099 predictions checked later**
- The readings already mark numbers (prices, benchmarks, speeds, dates) and statements.
- Want: a thing's numbers as a line (a model's benchmark scores across reports, a GPU's price), claims with who made
  them, predictions kept and checked when their date comes.

### 5. Since you looked and what changed (J, K): **0154 seen state**, **0094 since you last looked**, **0096 weekly what changed**, **0092/0136 back in the news**, **0159 surges against a subject's own past**
- The seen state exists per track (0207); News has read state per post (v10.26).
- Want: one "since you looked" across News and tracks; a weekly "what changed" (the track briefing's issue, for
  News); a subject back in the news after a quiet spell; a surge measured against the subject's own normal, not the
  feed's.

### 6. Relations between things (G, E): **0131 Stalker graph**, **0223/0224/0234 relations**
- Turned ON 2026-11-20 by the owner without their bars (acquired, part_of, partnered_with, derived based_on).
- Want next: measure them from the server's own rows and the owner's flags (I review first); the version line on the
  entity page (0220/0234, off); families (0230, reader rules off).

### 7. Facts about things (E, D): **0090 entities**, **0133 ent-v4 documents and cited sources**, **0229 cited documents**
- 43 fact rows for 359k entities: makers, dates, kinds live mostly in the readings, not as facts.
- Want: an entity's facts (maker, release date, size, licence, price) filled from its readings, each with its post;
  document originals and "Cited" (built in v10.25, off).

### 8. Asking questions (D, F, E): **0098 questions with citations**, **0100 study pages**, **0156 the knowledge page**
- Want: a question in words answered from your own posts and things, every claim cited; a study page per subject.
- Depends on 4, 7 and on retrieval; search by meaning is 0247 (written, skipped for now).

### 9. Sources and their worth (L, H, B, K): **0118 source track record**, **0093 noise per source**, **0132 voices and source analysis**, **0160 track suggestions**
- Want: per source, its fit per track (from the judgments), its noise (posts never in a story or track), its firsts,
  how often you open it; suggestions to tie or untie it from tracks; "switch off" suggestions for noise.

### 10. Discover with what we know (L, E, G): **0101 Discover with Mark X**
- Want: Discover suggesting the makers and people behind the things your tracks care about (the harness-hub case:
  the team behind adapters your sources discussed), not only sites your sources link.

### 11. Cost and size (C): **0244 data and CPU**, **0216**
- Task inputs pruned (v10.25); the duplicated post text per question kind is the remaining cost. Want: one stored
  input per post and window, referenced by its questions.

## Recommended order

1. **0245 track briefings** (v10.27): uses H, D, E as they are.
2. **Track lessons from the harness case** (v10.27, in 0245's build): always ask posts linked by followed sources or from
   tied sources; reject "confidence 0.0, not applicable" answers; re-ask old answers once when a track's guide changes;
   recency inside the Discover lane.
3. **3. Who said what first** (0157/0158): B and I are ready; it also feeds source value (9).
4. **5. Since you looked across News and tracks** (0154/0096).
5. **2. Earlier/later on a story** (0125), once the chain guide is improved.
6. **4. Numbers over time** (0095), then claims (0152).
7. **7. Facts about things**, then **8. Questions** (0098) — after 0247 is taken up.

Not now: 0099 predictions, 0100 study pages (they compose the above).
