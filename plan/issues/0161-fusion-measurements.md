# 0161 — Fusion's measurements: E1–E8, each on unseen posts, with a bar that decides its feature

Status: **spec** (2026-11-10). Research, run on the development machine. Runs before Fusion's step 2. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: `memory: held-out-testing`, `report-breakage-format`, `accuracy-over-quick-fixes`; the exploration
(private: `plan/research/fusion/README.md`, its guides in `guides/`, its tool `bin/fx`).

**Why this issue exists.** Fusion's evidence is two nights of fast exploration: one Haiku agent per experiment,
checking its own work on about 20 items. That finds directions; it adopts nothing. Each feature that changes what
INSIGHT reads or shows waits for one measurement here.

**Constraints (the owner's, standing):** no training, no PyTorch, nothing downloaded; Haiku by `claude -p` or as a
sub-agent, no API; calls kept well under 100 at a time; the live server by GET only; local copies read-only;
`plan/research/` private, never committed; the embedder only on request; a Starting Point pull only on the local
test instance, within politeness.

## The method, for every E
1. **Freeze** the guide (and any rule) first. Its text is not edited after the set is drawn.
2. **An unseen set:** posts no earlier experiment read. For AI news: the server's posts after 5 Nov 2026 (by GET).
   For other spheres: a fresh pull on the local test instance, sources not used on the two nights.
3. **Two blind labellers** (two Haiku runs with a labelling guide that never sees the system's answer, each
   reading the posts, never a script over words); **disagreements settled** by the main session reading the rows;
   **the owner spot-checks 20** rows per E, shown with the verdicts hidden.
4. **Report** as always: right, wrong, missed with exact rows, the cause, and the bar met or not, with its interval
   (Wilson). Private.
5. A failed bar changes the spec (or closes the feature), never the set.

## The measurements

| E | Decides | Set | Bars | Haiku calls (about) | The owner |
|---|---|---|---|---|---|
| **E1** events as the join | 0153 | 400 posts: 4 spheres (AI news and three others), 3 languages, one week each | see below | 120 | 20 rows, 15 min |
| **E2** the claims guide | 0152 | 150 posts, 3 spheres | a claim is in its post 95%; subject, speaker, number and basis 90%; an event date, when given, 90% | 70 | 20 rows |
| **E3** types | 0151 | 200 posts, 4 spheres + the lab's frozen AI sets | "other" under 10% per sphere; AI entity precision and `entity` candidate pairs not below today's | 50 | — |
| **E4** what a post adds | 0157 A | 150 later posts of events with earlier posts (needs E2's guide) | "repeats" right 95%; "new" missed as repeat under 3% | 60 | 20 rows |
| **E5** windows | 0150 C | 30 long posts, 3 spheres, up to 8 windows, one per call | a window's claims are in that window 95%; claims past 6,000 characters a reader would cite, found 85% | 90 (two sittings) | — |
| **E6** the knowledge page | 0156, 0158 B's writer | 5 subjects, 3 spheres (needs E2, E1) | lines supported 90%; 0 numbers or dates differing from their claims | 30 | 2 pages read, 15 min |
| **E7** track suggestions | 0160 | 15 suggestions from the owner's archive; 5 from one new sphere | 8 of 15 "would create"; at most 2 single stories, 2 duplicates; 3 of 5 usable in the new sphere | 20 | all 20, 10 min |
| **E8** the test-read | 0149 B | 60 sources, 3 spheres, **one source per call** | teaser / empty / paywalled found 95%; off-sphere found 80%; an in-sphere source called out under 5% | 60 | 10 sources |

### E1 in full (first, and the one the rest stand on)
- **Three arms on the same 400 posts:** (a) Mark IX's link rules; (b) **today's Mark X** — the candidates and the
  judge as shipped, run locally on the set (vectors from the embedder, on the owner's request); (c) events: the
  reading's main event, then one pass that assigns each post to an open event or opens one (0153's shape, as a
  script around `fx`).
- **The key:** two blind labellers each group the 400 posts by happening from their text (in batches of one
  sphere and one week, reading; grouping by a word-overlap script is not allowed — it invalidated one night's
  result). Their agreement is reported before anything is scored against it.
- **Scored per arm:** happenings with 2+ sources found; pairs right (precision) and pairs found (recall) against
  the key; cross-language happenings found; recurring subjects wrongly joined; per sphere.
- **Bars for 0153:** events' pair precision 95%, recall 80%; and, outside AI news, at least twice the multi-source
  happenings of arm (b) at no lower precision. If (b) already matches (c), 0153 shrinks to keys and state on Mark
  X's stories, and its candidate rules are widened instead (the `entity` source's types: 0151).
- Also recorded: spheres where no arm finds shared happenings (the 3D sphere's shape), as the evidence for a page
  of launches and work instead of News.

## Order and size
E1 → E2 → E3 and E8 (independent, the same night) → E5 → E4 → E6 → E7. About 500 Haiku calls in all, over four or
five nights at the standing limit; under $3 at the exploration's measured prices. The owner's part: about one hour
in all, most of it E1, E6 and E7.

## What does not need an E (built on counts instead)
0149 A and C, 0150 A and B, 0154, 0155, 0157 B, 0158 A, 0159: each is code, measured on the server copy or the lab
inside its own issue.

## Done when
- Each E has its report in `plan/research/fusion/measure/E<n>/` (private): the frozen guide, the set's ids, both
  labellers' rows, the settled key, the table, the exact rows.
- Each feature spec's status line is updated: adopted (bar met), changed (what and why), or closed.
