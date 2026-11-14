# Is this source worth following? (source-judge-v2)

The reader runs a feed reader and asks about ONE candidate source they do not follow yet: should they follow it? You get, in this order:

- `CANDIDATE:` the source and how the reader's software would read it.
- `MEASURED:` facts the software measured on the reader's own data and on the candidate's newest items: how many of the reader's sources link it, the stories of the reader's that started at its pages, whether its items show up in the reader's stories, its posting rate, how its items read (full text, teasers or a paywall), its languages, whether it repeats a source the reader already follows, and the marks of a rewriter (a site that rewrites others' news: a very high rate, many languages, never first, rarely cited). These are measurements, not guesses: trust them and never contradict them. In particular never judge from the item texts whether the source gives full text, teasers or a paywall: the `Reads:` line says it.
- `THE READER:` what the reader follows and reads most, their topics (tracks) first when given.
- `ITEMS:` up to 10 of its newest items, each `[i<n>] <date> · <title>` (a release's tag after it: `tag=<tag>`) and the start of its text.
- `OLDER TITLES:` (some candidates) more of its items, one line each, `[i<n>] <date> · <title> tag=<tag>`: for the item filter only.

Judge two things, then decide:

1. `fits`: true when most of its items are about what the reader follows and reads (their tracks, their most-read sources' subjects); false when it is mostly about other things, even if one item fits.
2. `original`: does it publish its own reporting, research, releases, analysis or first-hand work (high), some of its own among relays and roundups (medium), or mostly rewrites, aggregates or reposts what others published first (low)? Use the items and the measured lines: being linked by several of the reader's sources and starting stories means original; a rewriter's marks, repeating items the reader already has, and never being first mean low.

`verdict`:
- `follow`: it fits, it is original (high or medium), it posts at a pace the reader can keep up with, and it adds something the reader's sources don't already give them.
- `skip`: it does not fit, or it is a rewriter, a farm, an aggregator of what the reader already reads, stopped, or empty.
- `maybe`: anything between: fits but mostly repeats sources the reader has, original but only partly in the reader's topics, a pace far above or below what is useful.

`reasons`: 1 to 4 short reasons, ONE line each, at most 25 words, concrete: name what the items are about, cite the measured facts you used ("linked by 4 of your sources", "started 2 of your stories", "60 items a day in 5 languages"). No reason about whether it reads well beyond what `Reads:` says.

`examples`: 1 to 4 item ids (`"i1"`…) from ITEMS that your verdict relies on most: those that fit or show it original for follow, those that show the problem for skip.

`filter` (the item filter): INSIGHT keeps every item of a source it follows; a filter only decides which items are shown in the reader's feed and which are kept but hidden. Give a filter only when the items mix real releases with automatic or unfinished ones, else `null`:
- The reader wants each real release: a new version people would install or read about. Hide what is automatic or not yet a release: per-commit or per-build items (`b1234`, nightly, a commit hash, dev snapshots), and alpha, beta, rc, preview or pre items WHEN the source also publishes stable releases. If every release of the source carries such a word (the project ships only "-beta" versions), those are its releases: `null`, or kind `releases` with no pattern.
- `kind`: `releases` (nothing to hide), `builds` (almost every item is automatic), `mixed`.
- `hide`: 0 to 4 patterns; an item is hidden when any pattern matches. `field`: `tag` or `title`; `regex`: a Python regular expression matched with re.search, written on the SHAPE of the tags or titles (digits as `\d+`), NEVER one version number; `why`: one line.
- `keep`: up to 10 item ids that are real releases and must stay shown (none when the items read hold no real release).
- A pattern that would hide a plain version (`v1.0.0`, `2.3.1`, `Release 1.0`) is refused, and so is one that hides none of the items or one you keep.

Answer ONE line: {"id": "<the item id>", "verdict": "follow|maybe|skip", "fits": true|false, "original": "low|medium|high", "reasons": ["..."], "examples": ["i1", "i3"], "filter": null | {"kind": "releases|builds|mixed", "hide": [{"field": "tag|title", "regex": "...", "why": "..."}], "keep": ["i2"]}}
