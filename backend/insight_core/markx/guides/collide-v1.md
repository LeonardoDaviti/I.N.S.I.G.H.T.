# Name collision judge (Mark X 0119 A1, prompt collide-v1)

A news reader extracted named things (entities) from posts about AI and tech, English and Russian. One name key was found in several posts, but the extractor gave its mentions different types or makers, so the name may stand for more than one thing. Each item lists numbered mentions: how the post wrote the name, the extractor's type and its guessed maker (guesses, often wrong or loose), and the words around the name with the post's title.

Group the mentions into **senses**: one sense is one exact thing (one company, person, product, model, project, paper, place). The reader will give each sense its own page, so a wrong split scatters one thing's posts, and a missed split mixes two things on one page.

## How
1. Write `evidence` first: for each mention, a few words on what **the name itself refers to in its own sentence**, not on what the post is about. A post about a clone, a port, a rival, a fork or a thing built with X that names X is a mention of X itself ("a Windows port of X", "a rival copied X", "inspired by X": the name means X).
2. Then group. Two mentions are one sense when the contexts fit one thing. Split only when the contexts show **different things** (a model and an unrelated rocket company; one maker's coding assistant and another maker's chat assistant; a benchmark and an unrelated training course with the same name).
3. **Never split on the type or the maker field alone.** The extractor often types one product `software` in one post and `product` or `model` in another, and often guesses a maker from the name. A different maker counts only when the post's words name it.
4. Things tied to each other are related as `part`, never different: a company and its product, app or model family that carry the same name ("Acme" the company that ships "Acme" the app; a model family and the chat app built on it); a team, lab, unit or division named after its parent ("Acme AI", "Acme Research" inside Acme); a service and the company that runs it. Link every such pair in `related`.
5. Look for who makes or runs each thing. Two outlets, sites, projects, repositories or products with the same (or nearly the same) name but run by different owners are different things, even inside one field.
6. Another version or edition of the same family is `other_version`.
7. A sense needs positive evidence of what it is. A mention whose context doesn't say what the name refers to goes in `unclear`, never in a sense of its own; "I can't tell whether it's the same" is `unclear`, not a split.
8. Most of these names are one thing despite the differing fields. When in doubt, one sense.

## Output
One JSON line per item:
{"id": "<id>", "evidence": "1: ...; 2: ...", "senses": [{"m": [1, 2], "what": "a few words"}, {"m": [3], "what": "..."}], "related": [[1, 2, "part"]], "unclear": [], "confidence": 0.0}
- every mention number appears once, in one sense or in `unclear`; `related` uses the senses' positions (1-based); senses not related are different things;
- `confidence`: your probability (0 to 1) that the grouping is right.
