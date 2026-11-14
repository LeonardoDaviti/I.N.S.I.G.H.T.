# Sub-topic digest (digest-v1)

The reader keeps a TRACK (a topic in their own words) organised into SUB-TOPICS. You get the track, one sub-topic (its name and what it is about) and its newest POSTS, numbered [1], [2], ... each with who posted it, its date, its title and the start of its text.

Write a short digest the reader can read instead of opening every post:
- 2 to 4 `points`, each ONE sentence (at most 40 words) that says something concrete the posts say: what was built, used, tried, released or found, by whom, and what came of it. Synthesise: when several posts say the same thing, one point cites them all; when they disagree, say so.
- Each point lists in `cites` the numbers of the posts it rests on. Every point cites at least one post, and only posts that say what the point says. Say nothing the posts do not say: no outside knowledge, no guesses, no advice.
- Copy facts exactly: a number, a name, who did what and what one thing was compared with stay as the post gives them. When a point joins several posts, each claim must come from a post it cites; when in doubt, make two points.
- Never give a date the post's text does not give: the date beside a post is when it was posted, not when something happened.
- Plain words, no hype, no "this sub-topic covers"; name tools, people and numbers as the posts give them. Write in English whatever the posts' language.

Answer ONE line: {"id": "<the item id>", "points": [{"text": "...", "cites": [1, 3]}, ...]}
