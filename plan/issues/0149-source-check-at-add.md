# 0149 — Source check at add: what kind of source this is, whether it reads, whether it fits, and why none was found

Status: **spec** (2026-11-10). Fusion stage 1 (Capture). Parts A and C: Mark IX, no model, buildable now. Part B: a
Mark X task; **E8 (2026-11-10) passed it for fit and failed it for reads** (see "Measured"). Roadmap: `plan/INSIGHT_fusion_plan.md`.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; 0036 (the source doctor), 0135, 0137 (silent failures;
B5 "none says why"), 0148 (the track scout, section 3: its test-read is this issue's Part B, built once); the feed
finder; `memory: source-adding-rule`.

**Constraints:** every source add through the feed finder and page watching; fix the class, never a site; no real
names in committed files (rows: `plan/research/fusion/out/SP3*/`, `out/F9c/`, `out/F9d/`, private); tests stub every
request; keep everything; realdata-check once at release.

## Why
A new user started from one source in three spheres far from AI (a fresh INSIGHT, v10.13.1's image, rules only;
2026-11-10). Collecting worked: five sources reading well in 4–7 minutes. What went wrong was silent:

- **Bad sources look healthy:** a feed whose newest item was 772 days old; feeds of teasers; a feed of empty texts;
  a subreddit of bare links; a site's home page accepted as a feed.
- **Off-sphere sources are accepted without a word:** a general news feed followed into a 3D graphics sphere.
- **"None found" with no reason on 18 sites,** among them a parliament, a public broadcaster and two
  intergovernmental bodies. A site that could not be reached at all got the same answer. (0137 B5 added `reason`;
  these are the cases it still misses.)

Two cheap checks, both rough (one Haiku agent each, self-checked):
- **A plain rule, no model,** caught 5 of 7 of those silent failures. On the owner's own 251 sources it marks 114
  (41 with no text, 25 summary-only, 65 stopped). So it must be a **label per class, not an alarm**. Marked sources
  are read about half as often (13% against 26% of their posts opened), which says the labels mean something.
- **A test-read by Haiku** of each source's newest posts caught 4 of 4 teaser or empty sources and 3 of 6 off-sphere
  ones, and found a paywalled one. It confused spheres when sources of several spheres shared a call (13 of 63
  "out" verdicts wrong in one sphere).

## What it does
### A. Class labels, by rule (no model)
- For every source, from its newest 20 stored posts (or the finder's test fetch before it is followed):
  - `no_text`: most posts carry a title and no body;
  - `summary_only`: bodies are short and end cut, and full text was not fetched;
  - `links_only`: the body is a link and nothing else;
  - `stopped`: the newest post is older than the source's own rhythm allows (its usual gap, several times over; at
    least 30 days);
  - `undated`: dates are the first-seen time (0137 B9);
  - `not_a_feed`: the address answers a page, and page watching found no list of items.
- Thresholds: the ones the exploration used (`out/F9d/findings.txt`), re-measured on the server copy before they are
  frozen; none fitted to named sources.
- **Shown** in the Add-source dialog before following ("reads as: summaries only · last post 2 years ago"), on the
  source's row and in source health, as a label with its evidence (the counts). Never blocks a follow. Never counted
  as a failure in health's `errors` (0137 A1 keeps that meaning).
- Stored per source with the date computed; recomputed by the stats job (0132 B's), closed and reopened when it
  changes.

### B. The test-read (a Mark X task; after E8)
- Task kind `fit`, guide `fit-v1`: **one source per call**, its 10 newest posts (title and the first 600
  characters), and what the source is being added to: the track's description (0145), else the folder's name and
  the titles of 10 posts of its other sources.
- Answer: `reads` (full, teaser, empty, paywalled), `fit` (in, mixed, out), `about` (one line: what this source
  publishes), `confidence`.
- **When:** for 0148's scout candidates (its section 3 calls this); for a source followed into a track or folder,
  at the next worker run. Until then the row says "not test-read yet".
- **Shown** beside A's labels: "teasers only", "mostly not about <track>". A `fit: out` source is never removed; the
  owner sees it and decides.
- One sphere per call is a rule of the worker (0150 B), not of the guide.

### C. Why none was found
- The finder's answer separates, with the evidence it saw: **unreachable** (no answer, a name that does not
  resolve, a timeout), **blocked** (401 / 403 / 429 or a challenge page), **reachable, no feed and no list**
  (page watching found nothing to watch), **a feed that cannot be parsed** (the parser's message).
- First: re-run the 18 sites of the three spheres through today's finder on the lab and record which of 0137 B5's
  reasons each gets; this issue fixes the classes that still answer a bare "none found".
- The dialog offers the next step per reason: try again later (unreachable), page watching (no feed), "paste a feed
  address if you know one" (blocked).

## What the results should be
- A new user never follows a dead, empty or teaser source without being told.
- "None found" always carries one of four reasons.
- Of the 7 silent failures of the three spheres: A catches at least 5 at add time, A and B together all 7.
- On the owner's server: about 114 of 251 sources carry a class label, none of them an error.

## Done when
- Tests: each class on fixed feeds; a label never blocks a follow and never counts in `errors`; the `fit` schema,
  validation and one-source-per-call; each finder reason on stubbed answers.
- On the lab: the 18 sites listed with their reasons; the 7 silent failures with their labels.
- On the server copy: sources per class, and 10 random sources per class read by the agent (label right or wrong,
  exact rows, private).
- B is switched on only when E8 passes its bars.

## Measured (E8, 2026-11-10; private: `plan/research/fusion/measure/E8/REPORT.md`)
62 sources never test-read before in six spheres (Georgian news, climate, economy, health, space, football), each
offered to its own sphere, plus 24 offers of a source from an unrelated sphere; one source per call; two blind
labellers.

| | Result | Bar |
|---|---|---|
| A source of another sphere is found | 19 of 20 `out`, 1 `mixed` | 80%: met |
| An in-sphere source called `out` | 0 of 45 | under 5%: met |
| An in-sphere source called `mixed` | 7 of 45 (section feeds of general outlets) | — |
| Bad-reading sources found | 8 of 9 | 95%: not met |
| Full-text sources called teaser | **37 of 53** | — |

- **Part B is adopted for `fit` only.** Its `reads` answer is dropped: shown the first 600 characters of each post
  (as B specifies), the model calls a full article a teaser.
- **Part A's length rule is a label, not a verdict:** it flagged 5 of the 9 bad sources and 5 of 53 good ones; it
  cannot see a paywall after a long lede, or tell a complete short item from a cut one. Two labellers could not
  either (three wire feeds at 120–255 characters a post were called full).
- **New in Part A: reads is decided against the article's page.** Where full text is fetched, compare the stored
  text with the page's article length and the page's paywall marks: "the feed gives 180 of about 4,000 characters",
  "the page asks for a subscription". No model. This replaces `summary_only`'s guess from length and endings.
- Near spheres (an energy-markets source offered to an economy sphere) were not tested.
