# Track sub-topic placement (subtopic-place-v1)

The reader keeps a TRACK (a topic in their own words) organised into SUB-TOPICS. You get the track, its sub-topics keyed s1, s2, ... (each a name and, when given, what goes in it) and some of its POSTS keyed p1, p2, ... (title, one line on why the post is in the track, the start of its text).

Place each post in the ONE sub-topic a reader browsing the track would look for it in:
- Pick the sub-topic whose name and definition say what the post's MAIN subject is. A post that touches several goes where its main subject is.
- When no sub-topic fits its main subject, answer "none". Do not force a post into a sub-topic that only shares a word or a tool with it.
- Judge by what the post is about, not by its source or its format.

Answer ONE line: {"id": "<the item id>", "placements": [{"post": "p1", "subtopic": "s2"}, {"post": "p2", "subtopic": "none"}, ...]} with every post of the question once.
