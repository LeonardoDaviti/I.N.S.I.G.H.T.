# Story headline guide (Mark X F4, background run, prompt v2)

You see one news story: its core member posts from different sources (English and Russian), the earliest first, each with whose post it is (a repost reads "a post by its author shared by the feed"), platform, date, title and the start of its text. Write the headline a reader sees in their News list.

- `headline_en`: one English news headline of at most 14 words: who did what. Copy names, versions and numbers exactly as the members write them ("Claude Opus 5.5", "GPT-6.1 Terra", "$500bn"); never invent a figure or a version.
- What: the event most members report, the story's main subject. A member about something else (a side post, a reaction, a post that only mentions it) is not the story, even when it comes first.
- Who: the party the posts say did it. The maker releases its own product; a host, reseller, API hub, platform or app that offers, deploys or runs someone else's model or product is not its maker ("Acme Cloud adds Nimbus 5 to its API", not "Acme Cloud launches Nimbus 5"). A plan, paper, product or statement published on a company's own site or account is the company's act ("Acme publishes its plan ..."), even when its CEO posts a link to it, calls it "our plan" or a reporter names the CEO; name a person as the actor only when the posts say that person alone did it. A person who reposts, benchmarks or reviews a thing did not make it.
- When: the event is what is new on the members' dates, unless they say it happened on another date. A date the posts give for something earlier (the last time it happened, a precedent, an old release) is background: leave it out of the headline, so a reader never takes an old year for the event's ("Regulator ends the rule; its last use was 2019" is "Regulator ends the rule", not "Regulator ends the rule after 2019"). Give a date only as the posts state it for this event: a headline never names a year earlier than the members' dates unless the event itself happened then.
- Plain and factual: no hype, no question, no clickbait, no "BREAKING". Translate Russian into English.
- `summary_en`: one English sentence: what happened, with the key fact.

Return JSON only.
