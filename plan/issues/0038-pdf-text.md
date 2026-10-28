# 0038 — Reading the PDFs posts link to

Status: **future** (owner, 2026-10-28).

## Evidence (preview data, 2026-10-28)
- 104 posts link a PDF, from 8 sources: www-cdn.anthropic.com (41) and assets.anthropic.com (10) — system cards, research papers; cdn.openai.com (13) and deploymentsafety.openai.com (2) — system cards; a few from NVIDIA, NYU, GitHub.
- No post *is* a PDF; the PDFs are the substance behind announcement posts.

## Idea
- When a post's body is short and links one main PDF (a system card, a paper), read the PDF's text and keep it as the post's full text, or as an attachment section ("From the PDF: …").
- Needs one small library (e.g. pypdf); size S–M (tables and two-column layouts read poorly).
- After 0037: arXiv covers most papers without any PDF reading.
