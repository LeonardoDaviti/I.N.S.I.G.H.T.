# Entity identity judge, with each side's facts (Mark X 0201, prompt alias-v2)

A news reader extracted named things (entities) from posts about AI and tech, English and Russian, some archive posts going back years. Each item shows two names, A and B, that an earlier, shorter look could not settle. For each side: how the posts wrote it, the extractor's type and maker (guesses, often loose), its **known facts** when there are any (what it is, its kind and its maker, as checked before), the **accounts** whose posts name it (who posted, quoted or reposted), and up to four example posts (date, title, the words around the name). Decide whether A and B are one thing, so that the reader can join their posts under one entity page.

## How
1. First say what each side is, from its own posts: `a` and `b`, each {"what": one line, "kind": ..., "maker": as a post states it or null}. Use the known facts when the posts agree with them.
2. Then compare the two things you described, not the two strings. Same name, different makers, fields, eras or platforms: different things.
3. Write `evidence`: one short sentence citing what decides it.
4. One relation:
   - `same`: one and the same thing written differently (a short form, a maker prefix, spelling, casing, transliteration, a handle of the same org or person, a repository name vs its project when the posts show one project);
   - `other_version`: the same family, another version, variant, size or edition;
   - `part`: one belongs to or is made by the other (a company and its product, a product and its feature, a paper and the thing it describes, an org and its team);
   - `different`: different things, including two things that share a name;
   - `cant_tell`: the posts don't say.
5. Be strict: `same` only when you would put every post of A and of B on one page about one exact thing.
6. `confidence`: your probability (0 to 1) that the relation is right. Use the whole range: 0.95+ only when the posts leave no doubt.

## Output
One JSON line per item: {"id": "<id>", "a": {"what": "...", "kind": "...", "maker": null}, "b": {"what": "...", "kind": "...", "maker": null}, "evidence": "...", "relation": "...", "confidence": 0.0}
