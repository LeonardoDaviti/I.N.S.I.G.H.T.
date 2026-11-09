# 0144 — Stories for all history, and an entity page that shows a person's own posts, every story and each story's original

Status: **spec** (2026-11-09). Stealth (Mark X). Builds on 0086 (candidates, decide), 0112 (the reading window
setting, Decided 9), 0119 A (identity), 0132 (voices: a source that is a person), 0133 (`mx_mentions_now`), 0138
(the entity page: Original, rabbit hole, older guide). The timeline (0091) is **not** here: it is Stalker, built on
what this produces.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `markx/tasks.py` (`reading_window`, `PLAN_DAYS`),
`markx/decide.py` (`Config.days`), `markx/candidates.py`, `markx/entity_views.py` and the entity page (as 0138 left
them), `db/repo_voices.py`, `plan/issues/0138-built.md`.

**The owner (2026-11-09)**, on a well-known researcher's entity page (278 posts, 60 voices): "why there is no
original linked here? which is <his> own tweet of him building <a weekend project> / and also why there is no stories
created over so many posts? … I think that would be interesting to label everything that happened over past and have
full stories and timelines. that would make our database richer yes?" Then: "Yes I want spec 144 and agent on it."

**Constraints:** no real names in committed files (rows: `plan/research/0144-notes.md`); fix the class; keep
everything; never touch the live DB or the server except GETs; unit tests + 3–5 real checks; realdata-check runs once
at release (not by the agent).

## Why (measured on the server by GET, 2026-11-09)
- **The original is in the story but not on the page.** The weekend-project story (Mark X) has 4 posts, its first is
  the person's own post. The entity page lists only posts whose *text names* the entity, and a person's own post
  rarely names himself: 2 of the story's 4 show, not the original.
- **His own posts are missing.** INSIGHT follows six sources that are this person (X 1,343 posts, a video channel,
  two blogs, gists, an old blog); **55** of his own posts appear on his page.
- **275 of 278 posts are "in no Mark X story":** the decision window (`decide.Config.days`) is 30 days, so 232 of
  them were never asked. Older ones often sit in **Mark IX** stories (e.g. "joined <a lab>": his post and five
  channels that evening), which the page doesn't show.
- **Roles:** mention 158, subject 75, actor 28, venue 10, source 4 — a "what happened to him" view is the ~110
  subject/actor posts plus his own.

## What it does
### A. Stories for every post (the decision window as a setting)
1. **`story_window`** beside the reading window (`mx_settings`, days or `everything`, default 30), set on `/markx`
   like the reading window; read each run. `decide.Config.days`, the candidate finder's post range and `plan_checks`
   use it. News (`NEWS_DAYS`) is unchanged: old stories never enter News.
2. **The backfill is newest first** and resumable: candidates are found per day backwards from the window's newest
   day (the same rules: 72 h, other sources, the embedding/link/entity/burst sources); questions are planned in
   pages so a worker round mixes new and old.
3. **Old Mark IX stories are inputs, not answers:** a pair already in one Mark IX story is still asked (`check`, as
   today), so Mark X's stories over history are its own.
4. **Measured before switching to everything:** on the server copy, the candidate and question counts per window
   (30 / 120 / 365 / everything) and the decision run's time with the larger window (it must stay within its budget);
   the cost at the measured per-answer rate. Reported in 0144-built.md.

### B. The entity page: a person's own posts, every story, originals first
1. **"By":** an entity of type person (or org) linked to sources that **are** it — the voices link (0132: a source's
   voice is a person or org entity), or a source whose handle/profile names it by identity's key, confirmed once by
   the owner on the page ("These sources are <name>: yes / no") — lists those sources' posts with role **`by`**,
   counted in posts and voices, never in surges. Shown under "By <name>" apart from "About".
2. **Stories:** each Mark X story of the entity's posts, **and** each Mark IX story (marked "Mark IX") holding them
   when no Mark X story does; both list **all** their posts, not only the posts naming the entity.
3. **Original first:** a story's original is its root (Mark IX's `origin_url` / first post) or the earliest post by
   the entity itself; shown first in the story row, labelled "Original".
4. **Loose posts by role:** subject and actor first, then by, then mention collapsed ("158 mentions").

### C. Labels for the past (a sample, not everything)
- The page offers the owner a **sample** of old stories (10 per entity page visited, max 30 a day) with right /
  wrong / missed buttons; precision for stories older than 30 days is reported beside today's (≥ 0.97 to keep the
  window at everything; else it falls back to the last measured window and says why).

## Measure (3–5 real checks)
1. The owner's entity: own posts shown after B1 (expect ~1,300 by + the existing 278), the weekend-project story
   with its original first.
2. The counts in A4 per window, and the decision run's time.
3. After a night with `story_window = everything` on the server: stories created per year; a 20-story sample right /
   wrong (private rows).

## Done when
- Tests: the window setting read by decide, candidates and checks; News unchanged; backfill order and resume; "by"
  via voices and via the confirmed handle; a person's own post on his page; Mark IX stories shown when no Mark X
  one; the original rule; roles ordering; the sample's daily cap and the fallback rule.
- Migration if needed; frontend builds; vitest passes; design docs claim the new page parts and the setting.
