# New things in a track's sphere, by web search (websearch-sphere-v1)

The reader keeps a track: a sphere of interest named and described in their own words (what belongs, and what does not). INSIGHT looks for places to follow that it does not read yet. Each item gives the track's name, what belongs (`Belongs:`), what does not (`Not:`), the week it asks about, and the places already followed. Use your web search tool to find NEW projects, tools, makers and sites in that sphere from this week or this month: things people built and shared, and the people, teams and sites that make them.

How to search:
- At most the number of searches the item allows (never more). Search for what `Belongs:` names, with words like new, launched, released, built, show, this week, this month.
- Never open or fetch pages: the reader reads each address itself and judges its posts against the track.

What to return:
- For each find, its OWN address: the maker's site or blog, the maker's account (X, YouTube, Telegram, Bluesky, a code host or model hub account), or the project's own page or repository. Never news coverage of it: not an article, a news story, a review, a listing, a roundup, an aggregator, a forum thread, a search page or a directory.
- Only finds that belong by `Belongs:` and are not what `Not:` names; leave out the places the item lists as followed.
- Prefer makers and sites that publish again and again (a blog, an account, a channel) over a one-off page.
- An empty list is a good answer when nothing new fits.
- `url`: the address, exactly as found. `title`: the result's title. `why`: ONE line (at most 25 words): what it is and why it fits, e.g. "the maker's blog; launched a tiny open-source model this week".
- `queries`: each search you ran, as you typed it.

Answer per item: {"id": "<the item id>", "candidates": [{"url": "...", "title": "...", "why": "..."}], "queries": ["..."]}
