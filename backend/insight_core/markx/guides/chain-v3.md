# Story chain judge (Mark X 0219, prompt chain-v3)

A news reader keeps one line per named thing (a model, a product, a tool, a company's project): the stories about it, oldest first. Each item shows one THING (its name, type and maker) and two STORIES the reader filed about it: the EARLIER STORY and the LATER STORY (each its headline, its dates, and its earliest posts: date, source, how the post treats the thing, title), and the days between them. Some items show two sibling things instead (THING OF THE EARLIER STORY and THING OF THE LATER STORY: two things of one family, such as two models or two adapters of one line), each story with how its posts treat its own thing. Say how the later story relates to the earlier one. The reader sees your answer as a link between the two stories, so call a link only when you can see it in the headlines and posts.

## The relations (pick the first that fits)
1. `same_release`: both stories are about ONE release of the same exact thing (one version of a model, one product, one feature launch), at any of its stages and in the weeks around it:
   - before it: a rumour, a teaser, people waiting for it or complaining it is late, a preview, a waitlist;
   - the release itself: the official launch, its weights opened, availability on more platforms (an API, a model router, a cloud, an app, a plan, a country), its maker's own builds of it (GGUF, quantised or NVFP4 weights the same maker or org publishes), and support for running it added by an inference engine or a host around its release (day-0 support, a hosted endpoint, a recipe to serve it);
   - right after it: its own benchmark results and rankings (by anyone), its price, the maker's own details (system card, technical report, safeguards, a feature that came with it), and people trying it: first impressions, reviews, praise or complaints, demos of what it can do.
   Two stories of the same stage count (the launch filed twice, the same posts filed twice).
   Not `same_release`:
   - a result achieved WITH the thing: an open problem it solved, a proof or theorem it formalised, a discovery or research finding made with it, a scientific or engineering result its maker or anyone reports, even on the launch day and even when the maker announces it beside the release: the result is its own happening (`unrelated` here: the reader links it to the release through the thing itself). A demo of what it can do (a game, a scene, a page it built) and its benchmark scores stay `same_release`;
   - another party making a model or a study of its own from it: quantised or GGUF weights of its own, a fine-tune, a distillation or a merge, a study or test of one capability (law, safety, medicine): `builds_on`;
   - a benchmark, index or leaderboard launch about many models in which the thing is one entry among many: `unrelated` (unless the later story is about the thing's own first results);
   - a later new version, or a separate later update of a thing already out.
2. `same_launch` (only for an item showing two sibling things): the two stories are about two DIFFERENT things of one maker released as ONE launch, and you can see it in the posts: the maker's own announcement (a blog post, a launch post, a model card, a thread) names or covers both things, or the maker's launch posts present them as parts of one series (one name for the set, "the second of", "also today", the same launch link). A launch of several things together is one moment for the reader (two models announced together, a model and its smaller sibling in one post, several adapters in one release blog).
   Not `same_launch`:
   - each thing has its own launch: its own announcement on its own day, even of one maker, one family and a few days apart (a model's sizes released one after another, a model and its later point version, two products of one maker launched separately): `unrelated`;
   - one of the stories is another party's work on the thing (a fine-tune, a quantisation, a benchmark), or not about its thing's release at all: `unrelated` or `builds_on`;
   - the stories only share the family, the maker or the topic, or the posts do not show one announcement covering both: `unrelated`.
3. `same_event`: both stories report the same happening that is not a release (the same deal, incident, statement, lawsuit, filing): it was filed twice, nothing new happened between them.
4. `follows_up`: the later story reports the next step of the same non-release happening the earlier one reports: an outage resolved, a lawsuit's ruling, a filed IPO priced, a rumoured deal confirmed or denied, a promised change done.
5. `development`: the later story reports a new happening on the thing, after its release was over, that changes what the earlier story reported: a price cut or new limits, a feature added later, a reversal of the earlier decision, a ban after the earlier incident.
6. `reaction`: the later story is a named party's public response to the earlier story's happening (a rival's answer, an official's criticism, the maker's reply to earlier criticism). People trying a new release are not a reaction: that is `same_release`.
7. `builds_on`: the later story is someone else's own work that uses the earlier story's thing as its basis: quantised or GGUF weights of their own, a fine-tune, a distillation or merge, a product or paper built on it, a study that tests it for a purpose of its own.
8. `unrelated`: anything else. Both stories are about the thing but report separate happenings that do not touch each other (two features of one broad product, two unrelated updates), the two stories are about different versions or different things that share a name, or one of them is not really about the thing.

## How
- Judge the happenings, not the thing: sharing the thing is why the pair was proposed, and most proposed pairs of a broad product (an assistant, a platform, a company's app) are `unrelated`.
- Versions matter: two stories about different versions or variants (version 4 and version 5, a base model and its flash variant) are `unrelated` here (a successor is recorded elsewhere), unless the item shows two sibling things and the maker launched them as one (`same_launch`).
- `same_launch` needs the maker's own words tying the two together: quote in `reason` the post that ties them (its source and a few of its words). Two separate announcements are two launches.
- For a model or a product version, the stories of its first weeks are usually one release: check whether the later story is about that same version before you call it `unrelated`.
- When you hesitate between a link and `unrelated`, answer `unrelated`.
- Write `reason` first: one short sentence naming what in the two stories decides it.

## Output
One JSON line per item: {"id": "<id>", "reason": "...", "relation": "...", "confidence": 0-100}
