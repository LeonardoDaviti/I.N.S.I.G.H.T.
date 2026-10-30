# 0037 — Full arXiv papers, from their HTML version

Status: **future** (owner, 2026-10-28: "too far in the future, not important for now").

## Evidence (preview data, 2026-10-28)
- 3,439 of 7,720 posts (45%) are arXiv papers stored as their abstract only (about 1,450 characters each).
- arXiv publishes an HTML version at `https://arxiv.org/html/<id>`: 4 of the 5 newest papers had one, 52,000–128,000 characters each (the fifth answered 404).

## Idea
- For an `arxiv.org/abs/<id>` post, read `arxiv.org/html/<id>` with the existing article reader (no PDF, no new dependency); keep the abstract when there is no HTML version.
- New posts at fetch time, as full text does today; old posts through the full-text repair (a one-off, owner-run, polite: arXiv asks for a pause between requests).
- Size: S. Watch: math (MathML), figures, references; the page corpus (0032) gets one arXiv page first.

## Found while researching 0049 (2026-10-30)
- **A new version of a paper is a new post today.** The arXiv API feed links each version (`…/abs/2607.02689v1`, then `…v2`), so a revised paper is stored again. Sometimes the category feed's unversioned `…/abs/2606.28119` is stored a third time. On the preview, 3 papers take 7 rows.
- 0049 does not catch this: to a URL normalizer, `v1` and `v2` are different addresses. When this issue gives arXiv its own handling, store the paper once under its unversioned address, and treat a new version as an update (0039's "Updated"), not a new post.
