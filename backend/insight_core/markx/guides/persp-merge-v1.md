# Merge a story's fact lines (guide persp-merge-v1)

You get one item: a story's SUBJECT and its numbered FACT LINES, each with the source that added it. Group the lines that state the SAME fact, even in other words or with a rounder number ("3x faster" and "2-3x faster"; "$5 output" and "output costs 5 dollars"). Lines about different things stay apart, even when they share a number. When a line says an earlier figure is wrong, or two lines give conflicting figures for the same thing, keep them in one group and set `correction: true`, with the merged line stating both ("output $5 per million, not $2 as first reported").

Every line number appears in exactly one group. `fact`: the group's merged line in English, short, keeping every number.

Answer one JSON line: {"id": "<item id>", "groups": [{"lines": [1, 4], "fact": "...", "correction": false}]}
