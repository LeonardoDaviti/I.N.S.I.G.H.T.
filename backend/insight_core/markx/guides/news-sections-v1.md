# News sections guide (Mark X News, prompt news-sections-v1)

You see a reader's News list: every row is one news story, keyed `[r1]`, `[r2]` ... in the list's own order (most important first). Each row shows its headline, its main subjects with their kind (`entities:`), the kind of happening when known (`type:`), how many sources reported it (`voices`), and, when the list was divided before, the section it was in last time (`last: s2`). Divide the list into sections so the reader can take it one part at a time, and title each section.

- 3 to 8 sections. Every row in exactly ONE section: no row left out, no row twice, only the keys shown.
- Group by what a reader would look for together: the field, topic or kind of news the rows share (what they are about, or what kind of happening they are). Group by the subject the row is mainly about, not by a name it mentions in passing.
- Titles: 2 to 4 words, concrete and parallel (all of the same sort, e.g. all topics, or all kinds of news), plain English, no emoji, no numbering, no dates, each title different. A reader should know from the title alone what is inside. Never a vague title ("News", "Updates", "Highlights", "Misc").
- "Other" only for 2 rows or fewer that fit nowhere; otherwise give them a real section.
- Stability: when `LAST TIME'S SECTIONS` are shown, keep those titles (exactly as written) for the sections whose content still fits, and keep a row in its last section unless it clearly belongs elsewhere. Make a new title only for content no old title fits; drop an old title nothing fits now.
- Order the sections by their most important row: the section holding r1 first, then the one holding the next lowest key, and so on. Inside a section list the keys in the list's order.
- No section much larger than the others if a natural split exists; no section of one row unless nothing else fits it.

Answer JSON only: {"sections": [{"title": "...", "row_ids": ["r1", "r4"]}, ...]}
