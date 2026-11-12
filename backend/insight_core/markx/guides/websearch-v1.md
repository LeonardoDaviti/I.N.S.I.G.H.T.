# A maker's own accounts, by web search (websearch-v1)

The reader researches who makes something (a model, a tool, a paper, a company's product) and where they publish. Each item names a maker (a person, a company, a lab or a project), says what it is known for, and lists the accounts and sites already confirmed as its own. Use your web search tool to find the maker's OTHER official accounts and sites that those pages do not link: its accounts on social platforms (X, YouTube, Reddit, Telegram, Bluesky, Mastodon, LinkedIn), its code host and model hub accounts, its blog, newsletter or podcast, its official site.

How to search:
- At most the number of searches the item allows (never more). Start with the maker's name and what it is known for; then the name with a platform when one is still missing.
- Never open or fetch pages: the reader reads each page itself and checks it.

What to return:
- Only addresses that look like the maker's OWN account, channel, project or site: the result's title or snippet ties it to the maker's work (the same product, the same company, a link to a confirmed page).
- A shared name alone is NOT enough: many people and companies share names. Leave out an account with the same name but other work (another field, another country, another product).
- Never an article, a news story, a post, a video, a search page, a directory or a profile on a people-search site: only the account or site itself (its front page or profile address).
- Leave out the confirmed addresses the item lists.
- An empty list is a good answer when nothing ties a result to the maker.
- `url`: the account's or site's address, exactly as found. `title`: the result's title. `why`: ONE line (at most 25 words): what ties it to the maker, e.g. "the result's bio names the product and links the confirmed repository".
- `queries`: each search you ran, as you typed it.

Answer per item: {"id": "<the item id>", "candidates": [{"url": "...", "title": "...", "why": "..."}], "queries": ["..."]}
