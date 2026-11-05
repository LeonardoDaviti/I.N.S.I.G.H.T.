# Daily briefing guide (Mark X F12, background run, prompt v1)

You see one day of a reader's News (AI and tech, English and Russian sources): up to ten stories, each with a key ([s1], [s2] ...), its headline, how many sources covered it, and a few of its posts (source, platform, time, title, start of text). Write that day's briefing for the reader.

- 5 to 7 lines, most important first: what matters most to someone following AI and tech (a major release, an incident, a policy or market move), not simply the story with the most posts. At most one line per story; fewer lines if the day has fewer stories.
- Each line: one or two English sentences stating what happened, with the key names, versions and figures copied exactly from the posts. Nothing the posts don't say: no outside knowledge, no speculation, no hype.
- Each line cites the story or stories it comes from by key.

Return JSON only: {"lines": [{"text": "...", "stories": ["s1"]}]}.
