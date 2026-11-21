# 0154 — Seen state: INSIGHT remembers what you saw, so "new since you last looked" is a query

Status: **spec** (2026-11-10). Fusion stage 7 (Pages). No model. Buildable now on entity pages and tracks; events
and knowledge pages join when they exist (0153, 0156). Realises 0094. Roadmap: `plan/INSIGHT_fusion_plan.md`.

Read first: 0094 (and its measure: build this on entity pages and tracks, not on stories), 0052 (what I read; the
interaction log), 0030 (continue where I stopped), `post_reader_state`, `post_interactions`; the entity page
(0119 A3), the track page (0145).

**Constraints:** keep everything; one reader today, a reader column from the start (the hosted tier); realdata-check
once at release.

## Why
- Asked to say "what changed" on a subject between two weeks from the posts alone, Haiku was right on 57% of lines
  (rough: private `plan/research/fusion/out/F5b`). It cannot know what the reader had already seen; nothing stores
  it.
- 0094 measured where this matters: of 31 multi-voice stories the owner opened, 1 gained posts afterwards. A story
  is opened once it has mostly happened. **Entity pages and tracks keep growing**, and are opened again.
- With the state stored, "what changed" needs no model: it is the rows that arrived after a time.

## What it does
### 1. The state
- `mx_seen`: reader, subject kind (entity, track, event, page), subject id, **seen at**, and the previous seen-at
  (so the page can still show what was new on this visit after it has been marked).
- Written when the subject's page is opened and stays open 3 seconds or more (not on hover cards, not by a search
  result).
- "Arrived" is always **the time INSIGHT stored the row** (a post's first-seen, a claim's or membership's
  `valid_from`), never the post's published date: an archive run's old posts are new to the reader.

### 2. What is new, per page
- **An entity page:** posts crediting it, by role; its new versions (identity's `next_version`); a surge; with
  0152 and 0153: new events, new numbers, a state that moved.
- **A track:** new items in, new Discover items, a new sub-topic, a suggested source.
- Shown as one line at the top ("12 new since 3 Nov: 2 versions, 9 posts, 1 surge") that filters the page to them,
  and a quiet mark on each new row. "Mark all seen" is the default on leaving; "keep as new" undoes it for a
  visit.

### 3. Rows that link to a page
- A subject's row (the entity list, the track list, search's entity cards) carries a count of what is new, only
  for subjects the reader has opened before. Never a badge on something never opened.

### 4. Not here
- Stories (0094's measure). The post's "what this adds" covers them (0157).
- Any notification outside the reader.

## What the results should be
- Opening an entity or a track a second time shows exactly what arrived since, and nothing the reader already saw.
- On the server copy, replaying the owner's own visits: per revisit, how many rows were new (the feature's worth:
  if most revisits show 0, the line stays hidden at 0 and costs nothing).

## Done when
- Migration; tests: the state written at 3 seconds; arrived by stored time; an archive's old posts count as new; a
  closed row (valid_to) is not new; counts only for opened subjects; "keep as new".
- Frontend builds; vitest; the design docs claim the line and the mark.
- The replay's table (private rows).
