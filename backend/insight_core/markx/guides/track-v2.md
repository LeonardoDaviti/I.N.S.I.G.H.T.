# Track judge (track-v2)

The reader keeps TRACKS: topics described in their own words ("cool project ideas", "things worth 3D printing", "cheap local AI setups"). Each item gives you ONE track and ONE post. Decide whether the post belongs in the track, as the reader would want it there.

Each item:
- TRACK: its name, `Belongs:` what belongs (the reader's words), `Not:` what does not (when given), `Sub-topics:` names to use (when given), and examples the reader marked in or out (when given; follow them).
- POST: the platform and source, the title, the text (cut), its first links.

How to decide:
- `in` is true only when the post's MAIN subject is something the description asks for, and the reader would be glad to find it in this track. A post that only mentions the topic in passing, a roundup with one matching line among many, a job ad, a sale or coupon, or a giveaway with nothing about the thing itself is out unless the description asks for it.
- Things the description names are in when they are the post's subject. When it asks for tools, apps, products or projects of a kind, a post about one of them is in: its release or new version, a new feature, a demo, how someone uses it or what they built with it, from its maker or from a user. Such a post needs no step-by-step detail to be in. What stays out is business news ABOUT a company (funding, hiring, deals, lawsuits, prices of a plan) and a tool of another kind than the description asks for.
- Anything under `Not:` is out, even when it otherwise fits.
- Judge the post's content, not its source: a source that usually fits can post something that doesn't, and the reverse.
- Do not guess beyond the text: when the post is too thin to tell what it is about (a bare link, a title only), `in` is false with a low confidence.
- `confidence` (0 to 1): how sure you are of your `in`, whichever way. 0.9+ only when the text leaves no doubt.
- `subtopic`: a short name (2-5 words, English) for the part of the track it fits, e.g. "storage and organisers", "home lab hardware"; one of the given sub-topics when they are listed and one fits; null when `in` is false.
- `why`: ONE line (at most 25 words) in the track's terms: what the post is, and why it is worth it for this track (for a 3D printing track: what to print and why; for a setups track: what hardware or software, at what cost and speed). When `in` is false, say briefly why not.

Answer per item: {"id": "<the item id>", "in": true|false, "confidence": 0.0-1.0, "subtopic": "..." | null, "why": "..."}
