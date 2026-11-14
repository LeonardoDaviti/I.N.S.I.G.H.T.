# Who announced it, and where do they announce? (websearch-official-v1)

The reader follows news through other people's posts and wants to follow the ORIGINAL source: the actor's own channel. Each item is one news event: its headline, up to 3 posts about it (their source, title and start), the things it names, and the actor INSIGHT guesses (or "unknown"). Use your web search tool to find:

1. `actor`: the company, lab, project or person whose OWN announcement this event is: the maker of the released thing, the company that announced the deal, the person who published the work. When the event is a third party's test, review or opinion of a thing, the actor is the thing's MAKER (the reader wants the maker's channel), and `official` is still true. `official` is false only when no actor announces such events itself: a lawsuit against it, a regulator's action, a leak or a scoop, a layoff or a deal only reporters tell; say why in `why_not`.
2. `thing_maker`: when the event is about a product, model, tool or paper, the name of its maker as found (else null).
3. `announcement`: the actor's own page or post of THIS event, when your search finds it (a blog post, a newsroom page, a release page, a post on the actor's own account); else null.
4. `channels`: the actor's own channels where it announces things like this, the most official first, at most 4: its blog or newsroom SECTION (e.g. https://example.com/blog/), its code repository's releases (https://github.com/<org>/<repo>/releases), its official X account, its Telegram channel, its YouTube channel. Only the actor's OWN channels: never a news outlet, an aggregator, a fan or community account, an employee's personal account (unless the actor IS that person), a docs page, a product or pricing page, a help article, a download page, a model card, a site's home page alone.

How to search:
- At most 4 searches. Start with the headline's key words and the actor's name; then the actor's name with "blog", "releases" or "X" when a channel is still missing.
- Never open or fetch pages: the reader checks every address itself (who owns it, whether it publishes dated posts).
- A shared name alone is not enough: the result must tie the address to this actor's work (the same product, the same company, a link from its site).

Each `why` is ONE line, at most 25 words. `queries`: each search you ran, as typed.

Answer per item, ONE line: {"id": "<the item id>", "actor": {"name": "...", "site": "https://... | null", "kind": "org|person|project"} | null, "thing_maker": "... | null", "announcement": {"url": "...", "why": "..."} | null, "channels": [{"url": "...", "kind": "x|telegram|youtube|site_section|releases|repository|site|page|other", "why": "..."}], "official": true|false, "why_not": "... | null", "queries": ["..."]}
