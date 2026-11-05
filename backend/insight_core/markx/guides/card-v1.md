# Story card guide (Mark X F0.3, prompt v1)

You see the members of one news story (posts from different sources, English and Russian), the earliest first, each with its reading. Write the story's card in English:
- `headline_en`: one news headline of at most 14 words: who did what, with exact versions. Prefer the event the reports share, not a hook.
- `actors`, `object`, `action`, `date`: the event slots, as in the reading guide.
- `summary_en`: two sentences: what happened, and what is known so far.
- `kinds`: how many members are reports, commentary, roundups.
- `odd`: the ids of members that are NOT about this event (a hook, a digest item, another event), or [].
Return only the JSON object.
