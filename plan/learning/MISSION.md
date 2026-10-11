# Mission: maintain INSIGHT like a senior engineer

## Why
The owner steers INSIGHT, a single-user reader built fast by one person and a series of AI agents. It grew to 99k lines, and about half is weight. The owner wants to judge design calls themselves (what to delete, where a seam belongs, when a layer is a pass-through), so that agents build the codebase they would build, slice by slice.

## Success looks like
- Apply the deletion test to any INSIGHT module, and say whether it earns its keep.
- Spot a pass-through layer or a hidden-not-deleted flag in a diff before approving it.
- Review a slice of `plan/issues/0005-minimal-codebase.md` and say whether it deepened or only moved code.
- Name a seam and its adapters, and say whether it's real (two adapters or more) or hypothetical (one).

## Constraints
- Lessons are published as INSIGHT blog posts under `/blog` (owner's choice), in the Mark IX design language.
- Every example comes from INSIGHT's own code and history, not toy code.
- Short sessions alongside real work on the codebase.

## Out of scope
- Rewriting the stack in another language.
- General interview-style algorithms and data structures.
