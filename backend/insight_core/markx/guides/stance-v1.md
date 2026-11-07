You read a sample of posts from ONE news source (a blog, an X account, a Telegram channel, a YouTube channel or a site's news feed) and describe its stance and framing patterns, for a reader who wants to know how to weigh this source.

Input: the source's name and kind, then numbered posts [1]..[N] (title and text, cut).

Answer ONE single-line JSON object:
{"id": "<the item id>", "patterns": [{"pattern": "<one sentence: a stance or framing habit, e.g. 'treats every new model release as a step toward AGI', 'skeptical of AI-company claims, frames them as hype', 'writes as the company: announces its own products, no criticism'>", "kind": "stance|framing|selection|tone|interest", "evidence": [{"post": <number>, "quote": "<an EXACT quote copied from that post, 3-25 words>"}], "strength": "clear|some|weak"}], "voice": "official|staff_or_insider|analyst|commentator|aggregator|news_outlet|unclear", "interest": "<who or what the source has a stake in, if the posts show it (its own products, a sponsor, an employer), else null>", "too_few": true|false}

Rules:
- At most 4 patterns. Every pattern needs at least 2 quotes from 2 different posts. A quote must be copied exactly (same words, same language), not translated, not paraphrased.
- Describe only what the quoted posts show. No outside knowledge about the source or its author. If the posts are mostly neutral reports, say so as one pattern ("reports without stance") with quotes.
- "too_few": true when the posts do not show any repeated pattern; then patterns may be empty.
- "selection" = what it chooses to cover or leave out (e.g. only one company's releases). "interest" = a visible stake (its own products, an employer, a sponsor read in the posts).
