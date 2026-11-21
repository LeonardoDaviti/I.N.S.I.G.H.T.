# 0146 — Lasting importance: old stories that later news keeps building on

Status: **discussion, Stalker (future)** (2026-11-09). Not built in Stealth. Belongs beside the timeline (0091) and
the graph (0131): Stalker = Remember + Reason.

**The owner (2026-11-09):** "with time, new news cover older news (stories) which are more important than newest
happening, does insight somehow prevent that knowledge or importance loss? how?" → "Write it as discussion feature
for stalker in future."

## What already protects old knowledge
| Feature | What it does | Its limit |
|---|---|---|
| Keep everything | Nothing is ever deleted (posts, stories, News, Classics). | Kept is not surfaced. |
| Classics (0051) | A page cited again by many voices across months. | Pages only, not events; a story with no single page can't be a Classic. |
| Back in the news (0136, Shadow) | A new post that continues an old story brings it back on the Mark X News tab, judged by `back`. | Fires on a development; a post that only cites an old story as background doesn't count. |
| Stories over all history (0144) | Old posts get stories and originals; entity pages list them. | A dated list, no weight. |
| Entities and surges (0119) | An entity's page gathers everything; surges flag bursts. | Surges are about now. |

**Missing:** importance that **accrues over time** — nothing counts how often later news points back at an older
story. Importance today is voices and recency.

## The idea
1. **Every story collects later references:** posts of later weeks that point back at it —
   - link its original (paper, post, filing, page);
   - name its main entity in role `background` (Mark X readings record it);
   - `back` judges them a development;
   - a long-read cites it as one of its cases (0142 B's essay pattern);
   - a Stalker edge (0131) `earlier`/`causes`/`follows` to it.
   Each reference keeps its evidence (the post, the kind, the voice, the date).
2. **Lasting importance:** later references weighted by distinct voices, by how far in time they come after the
   story (a story still cited a year later outranks one that was loud for one day), with a slow fade so a
   foundation stays one; never a single signal alone (ensembled, per the owner's rule).
3. **Where it shows:**
   - **"Still shaping today"** on News: the old stories most referenced this week, apart from new ones;
   - **"Foundations"** on entity pages and tracks (0145): the few stories later news keeps returning to, first;
   - **the timeline** (0091): landmark events drawn larger, passing ones smaller;
   - written reports and essays (0142) cite foundations first.

## Measure before building
- A gold set of 30 stories the owner calls foundational (a well-known researcher joining a lab; the coining of a
  term; a model release that changed the field) and 30 that were only loud: lasting importance must rank the first
  above the second (precision at the top 30, the owner's labels).
- Which reference kinds carry the signal (links vs background mentions vs `back` vs essay citations), measured
  apart before they are combined.

## Depends on
0144 (stories over all history, live since v10.11), 0136 (`back`), 0133 (roles incl. `background` in readings),
0131 (edges), 0091 (the timeline), 0142 (essays as gold groupings).

## Open (the owner)
1. How fast a reference fades (a half-life of months, years, or none for links to an original).
2. Whether "Still shaping today" sits inside News or as its own tab.

## Measured (2026-11-20; private: `plan/research/fusion/measure/x1120/L0146/`)
72 older candidates (30+ days) reached from 150 current posts, labelled by two blind Haiku checkers (62 agreed, 10 settled). Lasting 35, mentioned 33, unrelated 4.
| Signal | precision of "lasting" |
|---|---|
| later posts linking back, top 20 | 85% (64-95) |
| distinct later sources >= 3 | 79% (60-90) |
| later posts >= 5 AND later sources >= 3 | 86% (65-95), recall 18 of 35 |
| Haiku judge on titles | 64% (46-79) |
Failure classes: a source's links to its own older posts, boilerplate links (an anniversary line), and next versions read as "building on". **A first slice is viable with no model:** count only other sources' links, a>=5 and b>=3, shown as a marked section; re-measure on a larger set.

## Measured again (2026-11-22; private: `plan/research/fusion/measure/x1122/L2/`)
156 candidates (116 walked back from 700 current posts, 40 random older posts with 1-2 later links); the full list of later posts from `GET /api/posts/item/<id>/connected?all=true`.
- Rule chosen on half: **at least 5 later posts from at least 4 other sources: 85% (64-95) on the held-out half,** 77% (61-88) over all 156; recall 27 of 44.
- All 8 wrong rows shown were the owner's saved pages (tools, repos, references): excluding saved pages is the next rule, found after the fact, so it needs a fresh set. The boilerplate and next-version filters barely fired.
- Missed: 11 of the 17 missed lasting rows are one source's own thread (by design, not counted).
- **Shape:** a marked "Still referenced" section on News and entity pages, not a claim.
