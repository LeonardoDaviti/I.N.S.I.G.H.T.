# 0148 — Track scout: a track finds sources in a sphere INSIGHT doesn't read yet

Status: **spec** (2026-11-10). Stealth, after 0145 (tracks as topics) and beside 0147 (track recall). The ingestion
half is Mark IX's: it reuses the feed finder, page watching and the source doctor, and inherits the "new spheres"
fixes (0135, 0137).

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `plan/issues/0145-tracks-as-topics.md`, `0145-built.md`,
`0147-track-recall.md`; `plan/issues/0135-new-spheres-silent-failures.md` and `0137-new-spheres-round-2.md` (what
broke when INSIGHT met a new sphere); the feed finder (0108), page watching, `memory: source-adding-rule`.

**The owner (2026-11-10):** "weakest things are for Cool 3D Projects … we don't have feed for 3D projects, its totally
new sphere, our worker should go beyond." And: "is it somehow connected to our experiments on totally different
spheres we had?"

**Constraints:** every source add through the feed finder and page watching; nothing followed without the owner's
tap; fix the class, never a site (no site lists in code: candidate shapes are platform classes); no fetches from
the development machine (the server's fetcher only; tests stub every request); keep everything; no real names in
committed files (rows: `plan/research/0148-notes.md`); unit tests + 3–5 real checks; realdata-check once at release.

## Why (measured on the server by GET, 2026-11-09)
- A track can only judge posts INSIGHT already fetched. "Cool 3D Projects" judged 168 posts on its first night:
  **6 in** (all from the one 3D source the owner added), **1** passive match. The other tracks (projects, local
  setups, agent workflows) found 22–65 each, because INSIGHT's sources already cover them.
- **The connection to the new-spheres experiments (0135, 0137, "Starting Point"):** those started from one source in
  another sphere and built its sources by hand, finding that **9 of 17 new sources failed silently** (RDF feeds,
  empty fetches, transcript language, dates). The track scout is the same move made automatic and repeatable: a
  track names a sphere, the scout finds its sources, and those sources go through the ingestion paths 0135 and 0137
  hardened. A new sphere is where silent failures surface, so every scouted source is test-read and its health
  shown before the owner follows it.

## What it does
### 1. When a track scouts
- On the owner's tap ("Find sources for this track") on the Topic view; and automatically, once a week, for a track
  with **fewer than 5 items in or ✓ in 7 days**.

### 2. Candidates, from three finders (no fetch yet)
1. **From the track's own matches:** link targets and quoted accounts of its in and ✓ posts — a site, a channel, a
   subreddit, an account — by Discover's address key (0050), not followed, not a product's or app's page.
2. **From platform shapes for the sphere:** for each platform class INSIGHT can read (a subreddit, a video channel,
   a Telegram channel, an X account, a blog feed, a model or project hub's listing, a platform's **search feed** for
   the track's terms where the platform offers one), candidates built from the track's words (0147's learned terms,
   or the description's nouns) and the names in its in-items.
3. **Haiku's suggestions:** one `scout` task (guide `scout-v1`): given the description, excludes and the 10 best
   items, name 20–30 likely sources with their platform and address or handle, and why. Never trusted as is: each
   goes through 3.

### 3. Every candidate is test-read (the server's fetcher, polite)
- The feed finder resolves it (feed, page watching, or "can't read: <why>", 0137's reason); up to 20 newest items
  read **into a scratch area** (not the archive, not the feed, nothing followed).
- The track's judge (`track` tasks, as 0145) rates those items; precision = in / judged.
- Health from the read: dates found, text length, language, transcript present (0135's classes). A candidate that
  reads empty or undated is shown as "can't read well: <why>", never suggested as working.

### 4. Suggested, ranked by precision
- On the Topic view, "Sources for this track": "<source> (<platform>): 14 of its last 20 posts fit · 3 a week ·
  reads well" with **Follow as active**, **Follow as passive**, **Not this one**. Following goes through the normal
  add path (feed finder, page watching). Below 30% precision: not shown.
- The main Discover gets the same rows under the track's name.
- A followed scout source records where it came from (the track, the scout run), so its later precision is shown.

### 5. Cost guard
- Per scout run: at most 40 candidates test-read, 800 judgements (≈ $0.15), one `scout` call (≈ $0.01); the
  server's request budget for test reads is its own and logged.

## Measure (3–5 real checks)
1. "Cool 3D Projects" after one scout: candidates per finder, how many read well, how many reach ≥ 50% precision,
   and the owner's follows.
2. One more sphere far from AI (the owner picks; e.g. the health/psychology sphere of 0135's Starting Point): the
   same counts, and the silent-failure classes met (should be 0135/0137's, now caught).
3. The judgements and requests spent per run.

## Done when
- Tests (stubbed requests): the weekly trigger and the tap; each finder's candidates (match links, platform shapes
  with search feeds, the `scout` task's schema and validation); the test read into a scratch area (nothing
  followed, nothing in the feed); health reasons; ranking by precision and the 30% floor; follow as active/passive
  through the add path; the provenance on followed sources; the cost guard.
- Worker: `scout` in `DEFAULT_KINDS`, `PER_CALL` `scout=1`; a fake-claude test.
- Migration; frontend builds; vitest passes; design docs claim the Topic view's sources block.
