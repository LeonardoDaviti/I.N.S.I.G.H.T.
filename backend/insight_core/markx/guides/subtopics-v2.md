# Track sub-topic names (subtopics-v2)

The reader keeps a TRACK: a topic in their own words. INSIGHT has already grouped the track's posts by what they are about. You get the track (its name and what belongs), the names already in use for its other groups, and the GROUPS to name, each keyed g1, g2, ... with how many posts it holds and up to eight of its newest posts (title, then one line on why the post is in the track).

Name each group:
- `name`: 2-5 words, English, no numbering, no emoji: what the posts have in common, the way the reader would look for it ("terminal multiplexers for agents", "agent instruction files"). Concrete beats generic: name the kind of tool, method or thing, not "News" or "Updates". Never a name already in use, and no two groups the same name.
- `definition`: one line (at most 25 words) saying what goes in it.
- Name the group by what most of its posts share; ignore one post that does not fit.

Answer ONE line: {"id": "<the item id>", "names": [{"key": "g1", "name": "...", "definition": "..."}, ...]} with every group of the question named once.
