# Timeline stop judge (Mark X 0165 C, prompt stop-v1)

A news reader keeps one page per named thing (a model, a product, a tool, a project) with a timeline: the stories about it, oldest first, each a stop on its line (it was teased, previewed, launched, benchmarked, ranked, its weights opened...). Each item shows one THING (its name, type and maker) and one STORY the reader filed (its headline, its dates, and its earliest posts: date, source, title, and how the post treats the thing: subject, actor or a mention). Decide whether the story is about the thing, and what happened to the thing in it.

## about (true or false)
- `true`: the thing is what the story is about, or one of its two or three main subjects (a launch of it, its results, its weights, an outage of it, a rival compared with it as the story's point).
- `false`: the story is about something else and only names the thing (an example, a comparison in passing, a list of many products, another product's launch that mentions it).

## stop (exactly one; for `about` false, still the story's own kind)
- `teaser`: hinted, teased, leaked or rumoured before it was announced, or said to be coming ("coming today", "soon", spotted in code).
- `preview`: announced or shown, not yet usable by most: a waitlist, early access, a research preview or beta, a demo, a date set.
- `launch`: it is first released or introduced (its first availability, the announcement that it is out).
- `availability`: a thing already out reaches more people or places: general availability, a new platform, country, API, plan, free tier or price.
- `update`: a new version, feature or change of a thing already out, including support it adds for something else (a new generation with its own new name is a `launch` of that name).
- `weights`: its weights, code or source opened (open weights, open-sourced, released on a model hub).
- `benchmark`: evaluation results, scores or tests of it (by its maker or others).
- `ranking`: its place on a leaderboard, arena or ranking against other things.
- `adoption`: someone else takes it up: uses, integrates, supports, ports, quantizes, deploys or sells it (a customer, an inference engine's support for it, a third party's build of it).
- `research`: a paper, technical report or detailed account of how it was built or trained.
- `incident`: an outage, bug, security flaw, misuse, recall, lawsuit, ban or controversy about it.
- `deal`: business news about it: funding, an acquisition, a partnership, its revenue or user numbers.
- `analysis`: opinion, review, comparison or a breakdown of it, no new happening.
- `other`: none of these.

## How
- Write `evidence` first: one short sentence citing what in the headline or the posts decides it.
- Judge the story as a whole (its headline and its earliest posts), not one post.
- When a story holds two happenings, choose what happened first in it to the thing (a launch with its scores is a `launch`; "coming today" then "out now" is a `teaser`).
- Read it from the THING's side: when the thing itself adds support for another model or tool, that is its own `update`; `adoption` is someone else taking the thing up. A platform hosting or selling another maker's products under an agreement is a `deal` for the platform.

## Output
One JSON line per item: {"id": "<id>", "evidence": "...", "about": true, "stop": "..."}
