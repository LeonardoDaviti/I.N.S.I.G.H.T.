# Back in the news (guide back-v3)

You get an OLD STORY (posts from two or more weeks earlier, earliest first) and NEW POSTS from one 72-hour window that a machine picked because they share a named thing, a web page or similar wording with the old story. Most such picks are NOT the old story coming back. Is the old story itself back in the news with something new?

## Step 1: the old thing
Write `old_thing`: the ONE specific thing or event the old story is about, as narrowly as the posts allow: a product or model with its exact version, a paper, an incident, a deal, a lawsuit, a person's act, an analysis or comparison, a giveaway or contest. If the old story is an analysis, review or opinion, the old thing is that analysis, not the topic it analysed.

## Step 2: each new post
For each new post, ask: does it report something NEW that HAPPENED to that same old thing, after the old story?
- Yes (a development): a release after a preview or rumour, open weights, general availability, a price, limit or terms change, a fix, a reversal, a ban, a court or regulator step, an outcome, an official response, a flaw or security issue found in it, a third party's measurement or reproduction that confirms or refutes its claims, the next step of that same event (the contest's results, the deal closing, the incident's cause found, the follow-up stream the giveaway promised), the same process moving on (the same IPO's next filing or investor day, the same lawsuit's next ruling, the same review's verdict), an official statement by the maker or an authority that names the old incident or thing and responds to it (even inside a wider statement). A statement that reports a NEW incident, even of the same kind by the same actor, is not a response to the old one.
- No, it is the same thing but nothing new happened: a recap, a late retelling, a comment, a meme, a user trying it or running it on their machine, a tutorial, a how-to, an opinion, a review or comparison after weeks of use, a timeline or analysis that recaps it, and third parties packaging it (quantisations, GGUFs, ports, wrappers, integrations, speed-up tricks by the community). That is `retold`.
- No, it is a different thing: another version, variant, size, revision or checkpoint of the same family (Haiku 5.5 vs Opus 5.5; GPT-6.1 Astra vs GPT-6 Astra; Spark 1.1 vs Spark; V4.1-Flash-1017 vs V4.1-Flash; Gemini 4 Carbon vs Gemini 4 Argon), even when the maker calls it an upgrade, update or refresh of the old one; another launch by the same company; another incident of the same kind by the same actor at a different target or place; a new analysis of the same topic; the same person doing something else. That is `related`.
  Check the names: write the exact name (with version, variant, date tag) of what the new post is about and compare it with the old thing's exact name. If any part of the version or tag differs, it is a different thing.
- No connection beyond shared words: `unrelated`.

## Step 3: the answer
For EVERY new post (by its number), write `about`: the exact name of the thing or event that post is about (with version, variant, date tag, place), then its `verdict`: `development`, `retold`, `related` or `unrelated` as defined above. Decide each post on its own. Before writing `development`, check: the post's `about` is exactly the old thing (same name, same version, same incident), and something new happened to it. If your own note says "different model", "different version", "separate incident" or "commentary", the verdict is not `development`.

Answer: {"id": "<id>", "old_thing": "...", "posts": [{"n": 1, "about": "...", "verdict": "..."}, ...], "what_new": "the new happening, or null"}
