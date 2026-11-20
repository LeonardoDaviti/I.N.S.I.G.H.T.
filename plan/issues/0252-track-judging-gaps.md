# 0252 — Track judging gaps: tied and linked posts always asked, junk verdicts rejected, guide upgrades re-asked, Discover by recency in bands, per track (v10.28)

Status: **built** (branch of v10.27), not merged, not pushed, not deployed. Migration **0165**. Real rows stay private
(the server walk's notes); every name below is invented.

## The case (server, 2026-11-20)

A track about agent workflows, read from the posts of one release of "harness adapters" (a lab's methods post and
community posts about it):

| post | where it stood | cause |
|---|---|---|
| the methods blog post | never asked, `below_bar` (probe bar 0.49) | the finders gate passive posts by their words only |
| a community post | judged in at 0.8, Discover position 759 of 3,089 (the lane shows 100) | Discover ordered by confidence: year-old 0.95s first |
| another community post | "out, confidence 0.0, Not applicable to this track." | an answer that judged nothing, stored as a verdict |
| older posts | answered under guide track-v1, never asked under track-v2 | a guide change asks only new questions |

## What was built (each in the module that owns the decision)

1. **Always asked** (`markx/finders.py`, two more finders, `ALWAYS`):
   - `source`: a post from a source **tied** to the track: a passive source the track already suggests
     (`tracks.suggestions`: SUGGEST_MIN+ posts in within 30 days, at least SUGGEST_SHARE of its posts; the share rule
     keeps general firehoses out);
   - `linked`: a post linked (post_links to its address) by `LINK_MIN` = 2+ of the track's sources (its active ones
     and the tied ones, never the post's own source).
   Both fire whatever the probe score and with or without a vector (the score query keeps a post with no vector only
   when one of them can fire); they come first in the union's order and count as "other hits" in the bar's budget
   (the budget's share is of embedded posts only). `INSIGHT_TRACK_FINDERS` can switch them off. `track_why` says
   `not_planned` with `found_by` for such a post not asked yet.
2. **No verdict, no "out"** (`markx/validate.py`, `track_verdict_error`, from the guide's own fields): `confidence`
   is "how sure you are of your `in`": 0 judges nothing. `why` is "what the post is": it must cite the post, i.e.
   share a word (5-letter stem, 4+ letters or with a digit) with the post's own title, text, links or quote that is
   none of the question's words (the guide's, the track header's) nor a function word; the platform/source line does
   not count. A post with fewer than 5 Latin-script words of its own is checked for the confidence only. A `track`
   task takes 2 attempts (`repo.KIND_ATTEMPTS`): one retry, then it fails and its rows keep no verdict; the page counts
   them `invalid` (not `waiting`), `track_why` says `invalid` with the error. Every answer stays in mx_calls.
3. **Guide upgrades re-ask** (`tracks._reask`, plan phase 4): the current description's verdicts answered under a guide
   other than the kind's, for posts of the last `REASK_DAYS` = 90, newest first, at most `REASK_PER_DAY` = 300 a track
   a day, after the new posts and the history pass, never a post the owner labelled. The row names the new task; the
   old task id goes to `mx_track_items.asked_before` (0165) with its answer kept in mx_calls; the old verdict is shown
   until the new task's first valid answer (`_fill` fills a row whose verdict is not its task's). Asked once: the new
   task has the current guide, so it is never picked again.
4. **Discover by recency in bands** (`tracks.discover_order`): bands of confidence `DISCOVER_BANDS` = (0.8, 0.6, 0),
   the bands ranked by calibrated precision at their edge (the edge itself until 10 labels), newest first within a
   band. The 100 cap stays; the page, the kept page's filled items and the why's position read the one order.
5. **Per track**: verified. Items, tasks (the track header is in the question), placements, sub-topics, the lane and
   the why are keyed by track and post; no code read one track per post. A test puts one post in two tracks (in
   Discover of one, judged out from the other's active source).

## Tests

`test_track_judging_0252` (15): verdict checks (cites the post, confidence 0, generic whys, the source line, another
script, no post), one retry, the new finders and the order; tied-source posts asked far from the bar and without a
vector; linked by 2 sources asked, by 1 not; the env switch; junk asked once more then invalid (counts, why); a retry
that is a verdict stored; the re-ask newest first, the day's cap, 90 days, labels skipped, the old answer kept, once;
Discover newest within bands with the cut and the why's position; one post in two tracks. Updated: test helpers' whys
now name their post (`test_markx_tracks.verdict`, scout, briefer, sub-topics, why), `ADOPTED`. Frontend:
`tracks.test.tsx` (found-by words, `invalid`, not planned by an ALWAYS finder); `tsc --noEmit` clean. The guide and
the schema are unchanged (no new guide id); worker tests run.

## To measure on real data (not done here: no server, no real rows)

- How many posts a day the `source` and `linked` finders add per track, and the judge's in-rate on them (the cost and
  whether tied sources bring fits); which of the track's passive sources pass the tie rule.
- The share of real `track` answers the new check rejects, read by hand: junk caught vs. good verdicts rejected (thin
  posts, non-English posts with an English why, titles that are only the track's words). Bar: rejections that are real
  verdicts under 1%.
- The re-ask: how many old-guide verdicts a track has in 90 days (days to finish at 300/day) and how many flip.
- Discover with the new order: the share of the 100 shown from the last 30 days, before and after.
