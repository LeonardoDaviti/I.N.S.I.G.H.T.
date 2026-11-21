# 0263 — Stories dated by their reports, never by a background page they cite

Status: **built** (v10.31). Case: `inkling-2-mini-release-row-dated-by-a-cited-paper` (plan/research/lab/cases.json).

## The bug (production 2026-11-21, after the v10.30 deploy)

A model release's Mark X story (8 voices: the maker's post, HN, several X posts, all 2026-11-20) gained a Saved
copy of an arXiv paper the maker's post cites, dated 2025-11-11 (`rule:citation`). Every story date was the minimum
over all its posts, so the story's first_at became 2025-11-11, News (stories begun in its window only) dropped the
release row (it was #1), and only a 2-voice benchmark split stayed.

How it joined: Mark IX's citation join lets a page you saved join its linkers **whatever its own date** (0113: a
page saved days later, or stating an older date, otherwise pulled its story apart; 31 of 50). That join is right
(the paper belongs on the release's page: Cited, originals); dating the story by it is not.

## The rule (utils/story_rules.py: `background`, `story_start`)

A post of **no voice** (voice.NOT_VOICE: a Saved page) dated more than `BACKGROUND_BEFORE` (= LINK_WITHIN, 72 h)
before its story's first post **of a voice** is background: it stays a member (its page, Cited, originals,
the tree), but it is never the story's start, its first post, nor the date News windows on. A post of a voice is
never background, however early: a leak days before a launch still begins its story (the teaser -> launch row).

Why this rule and not the others:
- *"A cited document much older than its citer is no member"*: would undo 0113 and the story page's Cited/originals
  display (the paper is rightly part of the release's page), and change membership, which more features read.
- *"Any member a later member links, > 1 day older, does not date"*: measured on the server copy (see
  plan/research/v1031/story-dates.md): 255 of 3,638 stories, 204 moves, nearly all wrong: a maker's or lab's own post
  cited by the coverage days later IS the story's start. Rejected.
- The voice rule reads what the date means (a report is a voice's; a page you saved is none), not how the page
  joined: it covers the citation join (production's case) and the address join (all 4 on the copy) alike. 72 h is
  the window inside which Mark IX joins any citation by date; only the Saved exception reaches past it.

One rule, read by every place that dates or orders a story: Mark IX's grouping (`Story.first_at`), News's rows
(`news_rules.news`: a background page sorts after the reports, so the row's first post and first_at are the
first report's; `_first` for the core names), Mark X's News rows (`markx/news.rows_of` and each story's kept first),
and Mark X's stored story date (`decide.persist` via `decide._start`). Both code stamps (NEWS_MODULES,
READING_MODULES) change, so the first run after the deploy makes News in full.

## Measured (server copy 2026-11-19, read only)

- Mark X: 4 of 3,638 current stories have such a page; all 4 first_at move (by 19 days to 5 months; 3/4 right,
  1 arguable: an arXiv paper dated 5 days before its first report). Mark IX: 6 of 3,798.
- The production case is not on the copy (newer); it is covered by test.

## Tests

`insight_core/tests/test_story_dates_0263.py` (pure, invented release "Glimmer 3"): a Saved paper a year older
is background and stays a member; Mark IX's grouping and News (Mark IX's and Mark X's row shape) keep the release
row with the maker's post first; a Saved page inside 72 h still dates; a voiced leak 30 h / 4 days before still
begins the story and the row; a cited paper of a source of its own (arxiv) is never background; Mark X's
`decide._start` the same.

## Left

- Mark IX's stored stories (6 on the copy) take the new date on their next regroup only (no backfill run).
- Production check after the deploy: the Inkling 2 Mini row back in Mark X News at its release date (the case is
  covered by test: `now` "pass" in cases.json).
