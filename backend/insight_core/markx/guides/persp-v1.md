# What a story member adds (guide persp-v3.2)

You get STORY items. Each has the story's SUBJECT, its ORIGINAL (the primary source; or the earliest report when none was found), then every member in PUBLISHED ORDER, then a JUDGE list of member ids. For EACH id in JUDGE, judge that member only, against the ORIGINAL plus the members published BEFORE it. Never describe another post; copy spans only from the judged member's own text.

Each member shows its address. "written by @x" means the post is @x's own words, carried by a repost or quote in another feed: judge it as @x's post (if @x made the thing, it is `original`). "[the maker's own account or staff]" is a hint from code, usually right but check it: a maker's one-line joke or reshare is still `same`.

ANYONE can be the maker: a lab, a company, a developer announcing their own tool or release, a blog or newsletter publishing its own post, a researcher posting their own paper, a channel announcing its own stream, event or service change, a podcast's own episode. A post by the maker about its own thing is `original`, even when it is small and even when the story has no other primary source. The EARLIEST REPORT by someone else (a third party retelling it) is `new_facts`, not `original`. When a SOURCE PAGE is given (members link it, no member is it), a LATER member that only retells, translates or summarises that page, or the earliest report, is `same` (or `opinion` if it argues); it is `new_facts` only for what it adds beyond them: its own tests, other sources, corrections, reactions of other parties, details the earlier members did not give.

An analysis or critique that states even one concrete new fact (a figure, a named detail, a finding from its own reading of the source) is `new_facts`, not `opinion`: list that fact.

A story is one happening. Members include: a minor leak hours before the release; reviews of the same document later; reproductions and replications of a paper; first tests, hands-on outputs and comparisons of a release; opinions written from the rumour just before the event; changes to the same product announced within a day or two; a repository implementing the announced design.

For each judged member, in this order:
1. `facts`: every concrete, STATED fact about THIS story's happening that is in neither the ORIGINAL nor any earlier member: a number, price, score, test or benchmark result, hands-on output, date, quote, detail, a correction, another party's statement. One line each in English, at most 4. `span`: an exact copy (5–25 words) from the member's text, in its language. `correction: true` when it says an earlier figure or claim is wrong. `about_story: false` when the fact is about something else (another model, another company's news, another item of a digest).
   NOT facts (put them in `claims` instead): estimates ("usually estimated at", "probably", "could be"), rumours, hearsay ("reportedly", "unverified reports say", "people on Twitter say"), predictions, promises ("I'll test it this week").
   Also NOT new: the same figure said in other words ("3x faster" after "2-3x faster"), a translation of what was said.
2. `claims`: unconfirmed claims as above, one line each with `span`; may be empty.
3. `label`, the first that applies:
   - `not_this_story`: its main subject is ANOTHER happening and this story is only premise or background (a model rumour built on an IPO; a company's staff talking about another product), or it is one item in a digest of unrelated news, or an unconfirmed dramatic "BREAKING" claim about a new development. A joke, meme, reaction, reshare or opinion about THIS happening is never `not_this_story` (it is `same` or `opinion`); neither is an opinion about this happening written from the rumour before it happened.
   - `original`: the primary source itself: the maker's announcement, its staff, team member or CEO announcing it ("we release", "our model"), the paper or its authors, the filing, the repository, the model card, release notes, or a bare link to one of those that NO earlier member already is or links.
   - `new_facts`: `facts` (about this story) is not empty.
   - `opinion`: no new facts, but it argues, interprets, criticises, disputes or predicts in more than one line; or it only carries `claims`.
   - `same`: restates what was already said, translates, reshares, a bare link to a page already in the story ("links the source"), "it's out", "wow", a joke, a one-line take even if it repeats a number, a promise to test later; also the maker's own later one-liners ("it's out!", "my favourite video") that add nothing to what is already in the story.
4. `point`: for `opinion`, the argument in one short English line; otherwise null.

Answer one JSON line per STORY item: {"id": "<story item id>", "members": [{"id": "<member id>", "facts": [{"fact": "...", "span": "...", "correction": false, "about_story": true}], "claims": [{"claim": "...", "span": "..."}], "label": "...", "point": null}]}
