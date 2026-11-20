# Track record format (track-schema-v1)

A reader follows a TRACK: a topic in their own words (its name, what belongs, what it excludes). Its posts come from blogs, social posts, forums and news. You design the record format the track's posts are read into: the kinds of THING the track is about, the units a reader would want listed and compared as rows (never the posts themselves).

- Propose 1 to 3 kinds. Use only what the track's name, description and excludes say or clearly imply; prefer fewer kinds; a kind is something many of its posts would describe. Never propose a kind for methods, habits, findings or opinions: a general kind `practice_or_claim` is always added for those.
- Each kind: `kind` (short snake_case), `about` (one line: what one row is), and up to 8 `fields`.
- Each field: `name` (short snake_case), `type`, `key`, `about` (a few words: what goes in it), and:
  - `type` "text": a short value in words;
  - `type` "number": a measured quantity; give `unit`, the usual unit;
  - `type` "money": a price or cost;
  - `type` "link": a page, repository, file or download link of the thing;
  - `type` "enum": one of a short list; give `values` (2 to 10, short, lower case, include "other").
- `key` is true for the 1 or 2 fields that tell the same thing apart across posts (its name, its link), false otherwise.
- Every kind's FIRST field is its name or title: type "text", key true. Add a "link" field when such things usually have a page, repository or file.

Answer ONE line: {"id": "<the item id>", "kinds": [{"kind": "...", "about": "...", "fields": [{"name": "...", "type": "text", "key": true, "about": "..."}, ...]}]}
