# Entity identity judge (Mark X 0119 A1, prompt alias-v1)

A news reader extracted named things (entities) from posts about AI and tech, English and Russian. Each item shows two names, A and B, with how the posts wrote them, their type, maker, version fields as the extractor gave them, how many posts name them, and one or two example posts (title and the words around the name). Decide whether A and B are one thing, so that the reader can join their posts under one entity page.

## Relations (exactly one)
- `same`: one and the same thing written differently: a short form ("Nimbus 5.5" = "Acme Nimbus 5.5"), a maker prefix ("Zeta Z200" = "Z200"), a social handle of the same org or person ("orbitlabs_ai" = "Orbit Labs"), spelling, casing, transliteration or language ("Акме" = "Acme"), a repository name vs its project name when the examples show it is the same project.
- `other_version`: the same family, but another version, variant, size or build ("Nimbus 5" vs "Nimbus 5.1"; "Orbit-6.1 Sol" vs "Orbit-6.1 Terra"; "Kestrel3.8" vs "Kestrel3.8-27B"; "Fable 4" vs "Fable 4 E4B"). A version number that differs anywhere ("4.1" vs "4.10", "K3" vs "K3.1") is never `same`.
- `part`: one belongs to or is made by the other: a company and its product or model ("Acme" vs "Acme Chat"; "Orbit Labs" vs "Orbit"), a product and its feature, an org and its team, a fork or a plugin of a project, a paper about a thing and the thing.
- `different`: different things, including two things that share a name (a model and an old space mission; a person and a product; two repositories with the same name by different owners).
- `cant_tell`: the examples don't say.

## How
- Write `evidence` first: one short sentence citing what in the names or examples decides it.
- Be strict: `same` only when you would put every post of A and of B on one page about one exact thing. When versions or variants differ, or one side names a version the other lacks, it is not `same` unless the examples show both posts mean the identical version.
- `confidence`: your probability (0 to 1) that the relation is right.

## Output
One JSON line per item: {"id": "<id>", "evidence": "...", "relation": "...", "confidence": 0.0}
