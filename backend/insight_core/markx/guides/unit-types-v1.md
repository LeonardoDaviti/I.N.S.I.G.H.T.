# Round-up items guide (Mark X, prompt unit-types-v1: one round-up's items, each its type and a headline)

You see some items of ONE round-up post from a personal news reader (AI, tech, science and business; English and Russian are equal): a daily or weekly digest, a newsletter, a link list. The first line names the round-up (its source, its title, its date). Each item is keyed `[u1]`, `[u2]` ... in the round-up's own order, with its words and the pages it links (`links:`). When the question starts mid-round-up, `(before u1: ...)` shows the item just before, for context only: do not answer it.

For EVERY item shown, answer its `type`, a `headline` and whether it `continues` the item before it.

## type (one per item: the kind of happening the item is MAINLY about)

| Type | The item ... |
|---|---|
| `model_release` | reports a new AI model, weights, checkpoint, quantisation or dataset made available. |
| `product_release` | reports a software or hardware product, tool, library, app, feature, version or price change that ships. |
| `research_result` | reports a new paper, study, experiment, benchmark, eval, leaderboard or scientific finding. |
| `business_event` | reports funding, an acquisition, a partnership, an IPO, a revenue or usage figure, a customer deal, layoffs, a hire or departure. |
| `policy_legal` | reports a law, regulation, court case, lawsuit, fine, government action or official investigation. |
| `incident` | reports an outage, breach, hack, vulnerability, accident, failure or harm that happened. |
| `public_statement` | reports what a notable person or organisation said: an interview, a claim, a letter, testimony. |
| `leak_rumour` | reports an unconfirmed or upcoming happening: a leak, "reportedly", "in talks", a teaser. |
| `opinion_analysis` | is an argument, essay, review, analysis, prediction or joke: its own view is the point. |
| `tutorial_explainer` | teaches or explains: a how-to, a guide, a concept explainer. |
| `community_post` | is a user's question, hands-on report, personal project or setup. |
| `promo` | promotes or sells: an ad or sponsor; the round-up author's own book, course, talk, podcast, event dates or appearances; a sign-up, subscribe or support line; a call for submissions ("send links"); or a bare link with nothing said about what it is. |
| `other` | anything else: an old story the round-up re-runs (an "N years ago" or archive item, a feature from months back, a link dated years earlier), fun or off-topic extras (photos, animals, games, trivia), the round-up's own intro or outro, a quote with no happening, an essay's reference link, contentless lines. |

Rules, in order:
1. **The item, not the round-up:** type what this item reports. A short news line in a digest ("X raised $2B (Reuters)") takes its happening's type.
2. **New beats old:** an item about something old (the round-up marks it as past, the link's date is years or months before the round-up's date) is `other`, whatever it reports.
3. **Reports beat commentary:** an item that mainly tells a new happening, with a take, gets the happening's type; an item that mainly argues is `opinion_analysis`.
4. **Promotion:** anything that sells, advertises or lists the author's own works or appearances is `promo`, never news.
5. **Off-topic fun** (a livestream of animals, a photo contest, a music release in a tech digest's "nice things") is `other`.
6. **Quoted reactions:** an item that quotes someone's post, tweet or comment giving a view, a take or a reaction ("X: I think…", "Y says this is bad") is `opinion_analysis`. `public_statement` only when what a notable person or organisation said is itself the news: an announcement-like claim, testimony, a policy statement, an interview the round-up reports.

## headline

What the item reports, in plain English, at most 14 words: who did what ("Acme limits data-centre clients' business abroad"). Not the round-up's words if they are only a fragment ("It told providers that…"): say the happening. For `promo` and `other`, a few words saying what it is ("The author's book tour dates"). No emoji, no source names in brackets, no ending period.

## continues

`true` only when the item is not a separate item but more of the item just before it (in the round-up's order): a second paragraph about the same release, a follow-up version of the same tool, "This release also adds…", "The 2.1 release notes list the change…", the same story's further links. Otherwise `false`. An item that names a different thing (another tool, another company, another story) is never a continuation, even when it is short ("Also out: gizmos v0.3.1" names another tool: `false`). The first item of a round-up is never a continuation.

Answer with ONE single-line JSON object for the whole question (never one line per item), starting with the question's id: {"id": "<the question's id>", "units": [{"key": "u1", "type": "...", "headline": "...", "continues": false}, {"key": "u2", ...}, ...]}: every key shown exactly once, in order, all in the one `units` array.
