# 0256 — Tracks take posts from any source: a blind check joins them (v10.29)

Status: **built, ON** (owner 2026-11-21: "not only sources but posts, because someone can post something related to
some track one day, it should be automatically categorized into track"; ranking accepted).

## Why

Every post of every source is judged for every track (Local Setups: 13,338 judged). A judged `in` from a source not
in the track went to Discover and joined the track only by 0207's band calibration: 20+ owner labels at 90%. The
owner had 7: nothing ever joined, so a track read only its own sources (Local Setups: 83 of 83 posts through one X
bridge, Agentic Workflows 59 of 59 Telegram, Cool Projects 72 of 76 GitHub) and the briefer (0245) never saw the
2,780 Discover posts of Local Setups. That gate was an owner-label gate (no-owner-label-gates).

## Measured (2026-11-21, the server's Discover lanes, read through GET; labelled blind by me)

- The judge's passive `in` alone: 47% right on 100 posts (3D 12%, Agentic 52%, Local 60%, Cool Projects 64%): a
  band join on the judge's confidence would flood the tracks.
- A blind second question (guide track-check-v1: "does the post GIVE the reader something of the track itself",
  field news out; it does not see the judge's answer), Haiku:
  - set A (100 posts, the threshold chosen here): in at >= 0.85: 27/27 right (Wilson 0.87); >= 0.7: 40/42.
  - set B (100 other posts, held out): in at >= 0.85: 26/27 (Wilson 0.82); the one miss is my label error (a
    printable PETG funnel with its STL, labelled from its title). Together ~53-54/54, Wilson ~0.93.
  - recall at 0.85: ~60% of the good posts (the rest stay in Discover, ranked as before).
- Private rows: `plan/research/v1029/track-check/` (to copy from /tmp/chk).

## Built

- `tracks.plan_checks` (the `track` planner's own phase, own cap CHECK_OPEN): each passive `in` of the current
  description, not labelled by the owner, newest first, asked once under track-check-v1 (subject post_track_check);
  the item row keeps the task and its answer (migration 0166: check_task_id, check_in, check_confidence, check_why,
  checked_at; an update marks the track changed, so the kept placement follows).
- `tracks.placed`: a passive `in` joins when its band joins (the owner's labels, as before) or its check says in at
  CHECK_JOIN (0.85). The owner's ✓ / ✗ wins. Switch `tracks.checked_join` (ON).
- The briefer reads joined posts (track_subtopics.in_track), so their things reach the brief.
- **Ranking** (accepted): the brief's rows by how many independent sources reported them, then newest; "· 3 sources".

## Next

- Source ties from the same data: a source whose checked joins are many and right is suggested to tie (0118/0160).
- Measure again on the server after a week of checks (the joined posts, blind), and the 3D track once it has sources.
