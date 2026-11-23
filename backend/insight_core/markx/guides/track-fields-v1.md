# Fields a track's records miss (track-fields-v1)

A reader follows a TRACK: a topic in their own words (its name, what belongs, what it excludes). Its posts are read into records: KINDS of thing, each with its fields (a name, a type). You see the kinds and fields the track has now, a sample of its ROWS (what was read into them) and a sample of its POSTS (titles and openings).

Propose the fields this reader would want added, so the rows can be compared and checked: what the posts keep saying that no field holds, or that one field mixes together (two quantities in one field, a value buried in a name or a summary).

- Ask of each kind what a reader comparing its rows asks: what it is made of or runs on (each part its own field), the quantities measured (one a field), what it gave (its result, the evidence for it), what it is compared with (the usual way, the version before), where it is explained (a post or page that explains it). Propose only those the posts state and no field holds.
- At most 6 fields over all kinds. Fewer is better: propose a field only when several of the shown posts or rows state such a value. None is a valid answer.
- Each field belongs to one of the KINDS shown (its `kind`, exactly as shown), never `practice_or_claim` (its fields are fixed; it is shown so you know what it holds). Never a field the kind already has, under any name.
- Each field: `kind`, `name` (short snake_case), `type`, `about` (a few words: what goes in it), `why` (one line: what in the sample shows it, naming a row or post), and:
  - `type` "text": a short value in words;
  - `type` "number": a measured quantity; give `unit`, the usual unit (one quantity a field: speed while generating and speed while reading the prompt are two fields);
  - `type` "money": a price or cost;
  - `type` "link": a page, repository, file, video or explainer post about the thing;
  - `type` "enum": one of a short list; give `values` (2 to 10, short, lower case, include "other").
- Use only what the track's words and the sample show; never a field about the post itself (its author, date, source).

Answer ONE line: {"id": "<the item id>", "fields": [{"kind": "...", "name": "...", "type": "number", "unit": "...", "about": "...", "why": "..."}, ...]}
