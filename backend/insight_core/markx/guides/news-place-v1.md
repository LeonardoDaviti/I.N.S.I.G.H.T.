# News placement guide (Mark X News, prompt news-place-v1)

A reader's News list is already divided into titled sections. You see those sections, keyed `[s1]`, `[s2]` ..., each with a few of its most important headlines as examples (`e.g.`), then the rows added to the list since, keyed `[r1]`, `[r2]` ... Each new row shows its headline, its main subjects with their kind (`entities:`), the kind of happening when known (`type:`) and how many sources reported it (`voices`). Put each new row into the section where a reader of this list would look for it.

- Every new row exactly once: no row left out, no row twice, only the keys shown.
- Judge by what the row is mainly about and what kind of news it is, the way the section's title and examples are; not by a name it mentions in passing.
- A section's title says what belongs in it; the examples show how it was used. A row fits a section when it is the same sort of news as those examples, even if it is about another company, person or place.
- Answer `"new"` only when no section fits at all: the row is a different field or kind of news than every section, and a reader would not look for it under any of the titles. Never `"new"` just because the row's subject is new; a catch-all section ("Other" and its like) takes a row that fits nothing else.
- When two sections both fit, choose the one whose title is closer to the row's main subject.

Answer JSON only: {"placements": [{"row_id": "r1", "section": "s2"}, {"row_id": "r2", "section": "new"}, ...]}
