# Where a story's sources differ (guide dispute-v1)

You get one STORY item: its SUBJECT, its ORIGINAL (line 0: the primary source or the earliest report, with its text), then numbered LINES. Each line is one fact (FACT) or unconfirmed claim (CLAIM) a source added, with the source's name and a QUOTE copied from that source's post.

Find the places where two or more DIFFERENT sources state DIFFERENT values for the SAME fact: a different number, price, score or date for the same thing; a different status (released vs preview, open weights vs API only); a different cause; a different attribution (who did or said it). Both statements must be about exactly the same thing, at the same moment, measured the same way.

NOT a difference (leave it out):
- an update over time: a count that grew ("115,000 signatures by Saturday", later "129,000"); a later announcement that supersedes an earlier plan, unless a source says the earlier figure was wrong;
- different things that share a unit: input vs output price, two different benchmarks, two model sizes, a range and one value inside it, a total vs a part;
- a rounder or more precise form of the same value ("about 12%" and "11.8%"; "3x" and "2-3x");
- one source correcting itself, or one source giving both values;
- an opinion, a prediction or a judgement against a fact; extra detail one source adds that another does not mention.

When in doubt, leave it out: show only differences a careful reader would call a real disagreement between sources.

For each difference:
- `fact`: what is in question, short, in English ("the base iPad mini's price").
- `sides`: two or more; each side is one value and the lines that state it: {"lines": [numbers], "says": "the value in a few words"}. Use line 0 for the ORIGINAL, and then give `quote`: an exact copy (5-25 words) of the ORIGINAL's text stating that value. A source appears on one side only.
- `kind`: one of number, date, status, cause, attribution, other.

Most stories have no difference: then answer an empty list.

Answer one JSON line: {"id": "<item id>", "disputes": [{"fact": "...", "kind": "number", "sides": [{"lines": [0], "says": "$799", "quote": "..."}, {"lines": [3], "says": "$699"}]}]}
