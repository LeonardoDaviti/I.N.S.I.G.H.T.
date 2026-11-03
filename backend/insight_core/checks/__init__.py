"""Real-data checks (issue 0075): the judged cases run, rules that hold on every post, and every
change's diff, on a copy of the owner's data.

- `cases`: each judged case has a machine-checkable `expect` (case.schema.json); the runner calls the
  services the pages call and says, per case, pass, fail or not checked
  (scripts/check_cases.py).
- `invariants`: checks over the whole copy, each a count and up to 5 example ids
  (scripts/check_invariants.py); a count above the baseline fails unless the spec names its reason.
- `snapshot` and `diff`: what a version of the code derives from a copy (titles, text starts, link
  titles, roundups, story membership, News, Classics, Discover), and what changed between two
  versions, by kind of change, with examples (scripts/realdata_diff.py).
- `scripts/realdata-check.sh <db>` runs all three before a merge: scratch copies of `<db>`, main's code
  on one, the branch's on the other, the report in plan/research/lab/checks/ (private).

The cases, the baselines and the reports hold the owner's data: they live in plan/research/
(gitignored), never in the repo. This package is generic code.

Version tolerance: realdata-check.sh copies this package into an older checkout (main, or a past commit)
to snapshot it, so it imports the app's functions defensively (`compat`) and never needs a newer app.
"""
