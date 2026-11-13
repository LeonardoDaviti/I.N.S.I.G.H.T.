# Name senses and identity facts (Mark X 0184, prompt collide-v2)

A news reader extracted named things (entities) from posts about AI and tech, English and Russian, some archive posts going back years. One name was found in several posts and the name may stand for more than one thing. Each item gives the name, sometimes the **known senses** already found for it (S1, S2, …: what each is, its kind and maker, two of its mentions), and numbered mentions: how the post wrote the name, the extractor's type and its guessed maker (guesses, often wrong or loose), the post's date and title and the words around the name.

Group the mentions into **senses**, one sense one exact thing (one company, person, product, model, project, paper, place, event), and say what each sense is. The reader gives each sense its own page and card, so a wrong split scatters one thing's posts, a missed split mixes two things on one page, and a wrong "what" or maker misinforms the reader.

## How
1. Write `evidence` first: for each mention, a few words on what **the name itself refers to in its own sentence**, not on what the post is about. A post about a clone, a port, a rival or a thing built with X that names X is a mention of X itself.
2. Group. Two mentions are one sense when the contexts fit one thing. Split only when the contexts show **different things**. Never split on the type or the maker field alone: the extractor often types one product `software` in one post and `product` in another, and guesses makers from the name. A different maker counts only when the post's words name it.
3. A company and its product, app or model family that carry the same name are **one sense** here when the posts can't tell them apart; when they can, they are two senses linked in `related` as `part` (never different).
4. When known senses are given, put each mention in a known sense (`"known": "S1"`) when its context fits it; a sense of yours with no `known` is a **new** thing. Only the mentions shown are grouped; the known senses' own mentions are context.
5. **A common word, not a name** (`generic`): the mention uses the word in its ordinary meaning ("a terminal", "the dashboard", "devs"), not as the name of one thing. Put such mentions in one sense with `"generic": true`. A capitalised word at the start of a sentence or in a title is still a common word if it means the ordinary thing. When in doubt it is a name.
6. A mention whose context doesn't say what the name refers to goes in `unclear`, never a sense of its own.
7. For each sense (new or known):
   - `what`: one line, at most 80 characters, what the thing is, as the posts show it ("a terminal app for running coding agents", "a 2003 PHP library for parsing RSS"); no praise, no guess beyond the posts and common knowledge;
   - `kind`: one of person, org, model, product, software, dataset, paper, event, place, project, law, other;
   - `maker`: who makes, runs or owns it **as a post states it** (the words of a post name the maker); `null` when no post says, even when you think you know. Never a guess;
   - `context`: up to 4 short words that tell this thing from another of the same name (a field, platform, place or era: "terminal", "2003", "RSS", "Grok");
8. Most of these names are one thing. When in doubt, one sense.

## Output
One JSON line per item:
{"id": "<id>", "evidence": "1: ...; 2: ...", "senses": [{"m": [1, 2], "known": "S1", "what": "...", "kind": "software", "maker": null, "context": ["terminal"], "generic": false}, {"m": [3], "what": "...", "kind": "other", "maker": null, "context": [], "generic": true}], "related": [[1, 2, "part"]], "unclear": [], "confidence": 0.0}
- every mention number appears once, in one sense or in `unclear`; `related` uses the senses' positions (1-based); senses not related are different things;
- a sense needs at least one mention; `known` only names a known sense given in the item;
- `confidence`: your probability (0 to 1) that the grouping is right.
