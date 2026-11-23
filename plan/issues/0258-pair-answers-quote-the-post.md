# 0258 — Join and pair answers quote the post they judged (v10.30)

Status: **built** (not deployed). Guide `judge-read-v2` (join and pair); `judge-read-v1` kept as their earlier guide.

## The case (found 2026-11-21 on the server)

The judge questions `join` (a post vs a story) and `pair` (a post vs a one-post story) share one guide and are asked in
batches. Haiku occasionally answers item A with another batch item's content. One task: STORY "Cursor added Claude
Fable 5.2, scoring 56.9% on CursorBench ..." vs POST "In 1983, physicists showed ... black holes form very abruptly ...
Fable 5.2 found the transition is abrupt there too." Two calls answered `same_event` (90, 88), with the reasons "Post
announces Fable 5.2 availability in Cursor with its CursorBench score" and "... the first physics problem of the
story". Neither describes this item: each was written from another question of its batch.

- right: none. wrong: both calls (`same_event` 90 and 88: the physics post is `mention` or `different`, its subject
  is a physics result, not the release). missed: the post's own subject.
- cause: batch answers are not tied to their own input. Nothing checked that a verdict rests on this post's words.

## Measured

About 1% of `same_event` reasons name things that are not in their input. This is an upper bound: translations
(a Russian post with an English reason) raise false alarms. The measure looked at reasons. It did not hold labels,
so it is not a precision figure.

## Built

- Guide `judge-read-v2` (markx/guides/judge-read-v2.md): v1's relations and notes, plus two quotes. `post_quote` is a
  short verbatim phrase of THIS question's POST title or text that the verdict rests on, in the post's own language.
  It may be "" only for `cant_tell`. `story_quote` is optional: for an "about" verdict, a phrase of the STORY. The guide
  says the questions may come in batches and each is answered from its own STORY and POST.
- schemas: `JUDGE_V2_SCHEMA` (post_quote required, both at most 300 characters). `join` and `pair` name judge-read-v2.
  `EARLIER_GUIDES` keeps judge-read-v1 for both kinds with its own schema (JUDGE_SCHEMA): its stored row loads
  unchanged (as join's, as before), and a v1 task still open is answered and checked under v1. `answer_guides(kind)`
  lists the current guide first, then the earlier ones.
- validate: `GUIDE_CHECKS["judge-read-v2"] = _judge_read`. `judge_blocks` splits the question as tasks.render_story
  + render_post build it: the STORY block, then the POST's title and text. The platform line, the links and the
  model's own "Reading of the post" are left out. The post quote must occur, folded (validate.fold, the same folding
  the span, stance and track_things quote checks use), in the POST's title or text. It must also be at least 12
  characters, unless it is the whole of a short title or text. A story quote, when given, must be in the STORY block.
  A quote of the story's own words given as the post's is refused, which is what this case does. `check(kind, ...)`
  with no guide now uses the kind's current guide's check.
- The retry path is unchanged. A refused answer is stored invalid with its error, and the task goes back to open
  (failed after 3 tries). scripts/markx-worker runs the same check before posting (`rule_error`: GUIDE_CHECKS by the
  batch's guide, imported from validate), so it asks the item again in the same cycle. The worker's code did not
  change.
- No re-ask of history. A question's task is looked up under judge-read-v2, then under judge-read-v1: in
  decide.Ask.answer, and in incremental.refresh's index, where the current guide's task wins when both exist. Every
  question already asked under v1 keeps its task and answers and is never asked again. Only new questions are asked
  under v2. The bounded re-asks that already exist (settle's second answer, `Ask.reopen`) reopen a v1 task under v1.
  The run key names the kinds' guides, so the first run after deploy is a full reading (not a re-ask).
- scripts/prep/scale.py: the fake worker quotes the POST under v2, so its calls stay valid.

## Not changed (noted)

- `check` (judge-raw-v1), `merge` (judge-story-v1) and `connect` (connect-v1) are batched too and could have the same
  cross-item answers. They are not changed here. Measure their rate first (Accuracy over quick fixes).
- The quote proves the answer read this post. It does not prove the relation is right: a grounded `same_event` can
  still be wrong.

## Measured later (on the server, after deploy)

- The rate of judge-read-v2 answers refused for `post_quote` / `story_quote` (mx_calls invalid with those errors,
  and the worker's `rule_invalid` and `invalid_errors` in its call log), split into: quotes from another batch item
  (the class this fixes), translated or paraphrased quotes (Haiku not copying verbatim: a guide wording issue), and
  quotes from the reading or links.
- Tasks failed after 3 tries on the quote alone. If that is more than a few per thousand, look at the cause before
  loosening anything.
- The ~1% of `same_event` reasons naming absent things, measured again on v2's answers. It should fall to about the
  translation false-alarm floor.
- Tests: test_markx_validate.JudgeQuotes0258 (an invented copy of this case: a cross-item answer refused, a grounded one
  accepted, v1 answers still valid under v1), test_markx_decide.Job.test_a_question_asked_under_judge_read_v1_is_read_never_asked_again,
  test_markx_api.EveryKindRoundTrips (join's invalid case is a story quote given as the post's),
  scripts/tests/test_markx_worker.TestJudgeQuotes0258.
