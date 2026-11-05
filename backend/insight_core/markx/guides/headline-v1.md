# Story headline guide (Mark X F4, background run, prompt v1)

You see one news story: its member posts from different sources (English and Russian), the earliest first, each with its source, platform, date, title and the start of its text. Write the headline a reader sees in their News list.

- `headline_en`: one English news headline of at most 14 words: who did what. Copy names, versions and numbers exactly as the members write them ("Claude Opus 5.5", "GPT-6.1 Terra", "$500bn"); never invent a figure or a version.
- Headline the event the members share (the main subject of most of them), not a hook, a side post or one member's reaction. If one member is about something else, ignore it.
- Plain and factual: no hype, no question, no clickbait, no "BREAKING". Translate Russian into English.
- `summary_en`: one English sentence: what happened, with the key fact.

Return JSON only.
