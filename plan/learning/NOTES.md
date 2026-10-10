# Teaching notes

- Lessons are INSIGHT blog posts, not standalone HTML: `frontend/src/blog/posts/*.tsx`, registered in `frontend/src/blog/posts.ts`, served at `/blog/:slug`. They live on the `experimental` branch.
- Reusable lesson components (figures, code excerpts, before/after compare, retrieval quiz, takeaway) are in `frontend/src/blog/components.tsx`. Build new lessons from them.
- Visuals: inline SVG using the Mark IX tokens only (`rgb(var(--text))` etc.), so they follow dark/light. Loudest element = inverted block. Dashed = planned, not built.
- Each lesson ends with a cheat sheet (the reference) and a "Read next" primary source. Lesson 1's glossary: `/blog/junior-to-senior#cheat-sheet`. Keep later lessons consistent with its terms.
- Quizzes: equal word counts per option, vary the position of the right answer.
- Every claim about INSIGHT should cite real code or a measured number (audit of 2026-10-10).

## Lessons

1. `/blog/junior-to-senior`: five junior habits (pass-through layers, copies, hidden-not-deleted flags, dead code, rebuilds) and their senior replacements.

## Next lesson candidates

- Do the deletion test hands-on on one real INSIGHT module, before slice 1 of issue 0003.
- Read a slice diff: did it deepen a module or only move code?
