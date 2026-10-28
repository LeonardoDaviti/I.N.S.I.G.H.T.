# 0037 — Full arXiv papers, from their HTML version

Status: **future** (owner, 2026-10-28: "too far in the future, not important for now").

## Evidence (preview data, 2026-10-28)
- 3,439 of 7,720 posts (45%) are arXiv papers stored as their abstract only (about 1,450 characters each).
- arXiv publishes an HTML version at `https://arxiv.org/html/<id>`: 4 of the 5 newest papers had one, 52,000–128,000 characters each (the fifth answered 404).

## Idea
- For an `arxiv.org/abs/<id>` post, read `arxiv.org/html/<id>` with the existing article reader (no PDF, no new dependency); keep the abstract when there is no HTML version.
- New posts at fetch time, as full text does today; old posts through the full-text repair (a one-off, owner-run, polite: arXiv asks for a pause between requests).
- Size: S. Watch: math (MathML), figures, references; the page corpus (0032) gets one arXiv page first.
