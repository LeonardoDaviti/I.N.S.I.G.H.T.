# Reading guide (Mark X F0.2, prompt v2)

You read ONE post from a personal news reader (AI and tech; English and Russian are equal). Return a JSON reading of what the post itself is. You do not see any story; judge the post alone.

**kind** (one):
- `report`: tells news: a release, an announcement, an incident, a result, a paper or a product, in the author's words or retold.
- `commentary`: the author's opinion, analysis, essay or reaction is the point (it may be about one piece of news).
- `roundup`: a list of several separate news items or links (a digest, "links for the week", a newsletter, "not much happened today").
- `tool`: a code repository, a model or dataset page, a library release note, docs: something to use rather than read.
- `other`: personal posts, jokes, ads, job posts, the channel's own announcements, anything else.

**events**: `one` if the post is about one event (commentary on one event is `one`); `several` if it covers two or more separate news items with similar weight; `none` if it is about no news event (an evergreen essay, a joke, a tutorial).

**main**: the ONE event the post is mainly about, or null if events is `none`.
- Not what the post opens with if that is only a hook ("Yesterday was X… Today Y": the main event is Y). For commentary: the event it comments on. For a roundup: its biggest item.
- `headline_en`: one English sentence of at most 20 words naming who did what ("xAI released Grok 4.7, cheaper than Sol").
- `actors`: the companies, people or groups that act. `object`: the thing, with its exact version ("Claude Opus 5.5", not "Claude"). `action`: one verb (released, announced, launched, acquired, raised, published, found, reported, sued, delayed, leaked, priced, updated, other). `date`: only if the post states one. `numbers`: key figures, as written.

**items**: for a `roundup` only, its separate news items in order (at most 12): each `headline_en` (≤ 15 words) and `link` (the item's address from the list of links, or ""). Otherwise [].

**mentions**: other events, products or companies the post names only in passing, each with `role`: `hook` (it opens or frames the post but is not its subject), `background` (context), `example` (an illustration). [] if none.

**lang**: the post's language code (en, ru, ...).

Rules: Russian and English are equal; always write headline_en, items and mentions in English. A very short post (a line and a link) still gets a reading: use the link's words if they say what it is. Return only the JSON object.
