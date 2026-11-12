# Rename judge (Mark X 0165 B, prompt rename-v1)

A news reader keeps one page per named thing (a model, a product, a tool, a project). Each item shows two names by one maker, OLD and NEW: OLD was written first and stopped being written about when NEW appeared (or soon after). For each name you see its type, its maker, how many posts name it, its first and its last post (date, source, title and the words around the name), the addresses its posts give as its own (a code repository, a release page), and why the reader asks (a shared address, a post saying "formerly" or "renamed", or NEW's post naming OLD). Decide whether NEW is the same thing as OLD under a new name, so the reader can show OLD as NEW's earlier name on one timeline.

## Relations (exactly one)
- `renamed`: one and the same thing, renamed: an experimental part of a bigger product released on its own under a shorter name ("Acme Forge Snap" becomes "Acme Snap"), a project rebranded ("Orbit Notes, formerly Kestrel Notes"), a code name replaced by the launch name, the same repository under a new name. The thing itself (what it does, its code) continues.
- `successor`: a new, different thing that replaces OLD or comes after it (a new product line, a rewrite announced as a new product, the next model). Another version of one family ("Nimbus 5" after "Nimbus 4") is a successor, never a rename.
- `part`: one is a part, feature, plugin or component of the other, and both go on existing.
- `different`: different things that only share a word or a maker.
- `cant_tell`: the posts don't say.

## How
- Write `evidence` first: one short sentence citing what in the posts decides it (a sentence saying it was renamed, the same repository, NEW's post describing OLD as what it was).
- Be strict: `renamed` only when you would put every post of OLD on NEW's page as its earlier name. A shared maker, a shared word or a similar purpose alone is not a rename.
- `confidence`: your probability (0 to 1) that the relation is right.

## Output
One JSON line per item: {"id": "<id>", "evidence": "...", "relation": "...", "confidence": 0.0}
