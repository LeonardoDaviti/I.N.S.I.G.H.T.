# Reading guide (Mark X, prompt read-v3: read-v2 + event type and origin; the lab's frozen rv3d without confirms_earlier)

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
- `headline_en`: one English sentence of at most 20 words naming who did what ("Acme released Widget 4.7, cheaper than Rival").
- `actors`: the companies, people or groups that act. `object`: the thing, with its exact version ("Widget Pro 5.5", not "Widget"). `action`: one verb (released, announced, launched, acquired, raised, published, found, reported, sued, delayed, leaked, priced, updated, other). `date`: only if the post states one. `numbers`: key figures, as written.

**items**: for a `roundup` only, its separate news items in order (at most 12): each `headline_en` (≤ 15 words) and `link` (the item's address from the list of links, or ""). Otherwise [].

**mentions**: other events, products or companies the post names only in passing, each with `role`: `hook` (it opens or frames the post but is not its subject), `background` (context), `example` (an illustration). [] if none.

**lang**: the post's language code (en, ru, ...).

**Consistency rule (enforced):** `main` is null if and only if `events` is `none`. When `events` is `several`, `main` MUST still name one event (the biggest item; for a roundup, its first or largest item). Never return `main: null` with `events: one` or `several`.

**event_type** and **origin**: as defined below. They describe the post's MAIN event (the one in `main`), or the post itself when `events` is `none`.

## Event types (one per post: the type of the happening the post is MAINLY about)
Type the main happening, not the author and not the tone. A maker's own launch post, a news site's retelling and a Telegram channel's translation of the same release all get the SAME type.

| Type | Definition | Includes | Not (goes elsewhere) |
|---|---|---|---|
| `model_release` | A new AI model, weights, fine-tune, quantisation or dataset is released or made available. | a lab's launch post, a model card, a Hugging Face page, "X is out", a model reaching an API or app, a new checkpoint or dataset | a teaser or "coming soon" (`leak_rumour`); a benchmark of an existing model (`research_result`); a review of it (`opinion_analysis`) |
| `product_release` | A software product, tool, library, app, feature, version, docs change, or price/plan change ships. | release notes, a repo launch, a new app feature, a version bump, a price cut, a hardware product launch | a model (`model_release`); a personal hobby setup with nothing released (`community_post`) |
| `research_result` | A new paper, study, experiment, benchmark, eval, leaderboard ranking or scientific finding. | an arXiv paper, a lab's research blog post, a new benchmark and its scores, a reproduction, a survey result | an essay arguing about research (`opinion_analysis`); an explainer of an old method (`tutorial_explainer`) |
| `business_event` | A corporate happening: funding, acquisition, partnership, IPO or filing, startup launch, revenue/usage/sales milestone, customer deal, layoffs, a hire or departure. | "raises $2B", "acquires", an S-1, "1B weekly users", an executive leaving | an official legal action (`policy_legal`); unconfirmed talks or "in talks to" (`leak_rumour`) |
| `policy_legal` | An official government, court, regulator or formal governance action. | a law, bill, regulation, court ruling, lawsuit filed, fine, visa or fee rule, a lab's formal policy commitment | a commentator's view of a policy (`opinion_analysis`); a government "considering" something (`leak_rumour`) |
| `incident` | Something harmful or broken that happened or was disclosed. | a breach, exploit, outage, data leak (of user data), model misbehaviour found in the wild, scraping scandal | a planned leak of an unreleased product (`leak_rumour`) |
| `public_statement` | A notable person's or organisation's remarks are themselves the news. | an interview, a podcast appearance, a CEO's claim, a public letter, testimony | an author's own essay (`opinion_analysis`); a statement that announces a release (type the release) |
| `promotion_event` | A program, event, course, book, grant, competition, meetup or sponsored offer is announced or promoted. | conference dates, "applications open", a hackathon, a discount, a book launch, a webinar | a product launch (`product_release`) |
| `leak_rumour` | An UNCONFIRMED or upcoming happening that a later official announcement could confirm. | a leak, a rumour, a teaser or countdown, "reportedly", "sources say", an exclusive report from unnamed sources, "in talks", "considering", "coming next week", an unsourced "BREAKING" | an official announcement of a future date ("launches on 3 March", said by the maker: type the release); personal or partisan allegations no official release will confirm (`other`) |
| `opinion_analysis` | The post's own argument, review, analysis, essay, prediction, reaction or joke is the point. | a review of a model, "why X matters", hot takes, memes and satire, evergreen and history essays, critique of a paper | a post that mainly reports a new happening with a little snark (type the happening) |
| `tutorial_explainer` | A how-to, guide or explainer of an existing technique, tool or concept. | "how to run X locally", a prompting guide, a concept explainer, a course lesson | a new tool's launch (`product_release`) |
| `digest` | A newsletter, roundup or recap covering several separate items, or a periodic issue. | "this week in AI", a channel's daily summary, a conference recap of many talks, a link list | a post about one item that mentions others in passing (type that item) |
| `community_post` | A user's question, poll, proposal, help request, hands-on report or personal project/setup showcase, not an official release. | "has anyone tried…", "my local rig", "I built a toy with X", a bug report | a released open-source project with a repo (`product_release`) |
| `other` | Anything else. | off-topic, personal anecdotes, trivia, vlogs, unclear or contentless posts, a bare link with no clue what it is, allegations | — |

Deciding rules, in order:
1. **Unconfirmed beats everything:** if the post's main happening is not yet official (leak, rumour, teaser, unnamed sources, "in talks"), it is `leak_rumour`, whatever the topic.
2. **Reports beat commentary:** a post that mainly tells a NEW happening, even with a joke or a take, gets that happening's type. A post that mainly argues and only cites a happening is `opinion_analysis`.
3. **Several items:** a post covering several separate news items with similar weight is `digest`.
4. **A first test of a new release** (hands-on outputs, "I tried it and…") is `opinion_analysis` if it is a reaction, `research_result` if it is a measured benchmark/eval with numbers.
5. **No happening at all:** form decides: `opinion_analysis` (argues), `tutorial_explainer` (teaches), `community_post` (asks or shows a personal project), `other`.

## Origin (who the post is, relative to its main happening)
- `maker`: the post is the maker's own announcement or primary document: written by the company, lab, project, author or agency that DID the happening (its account, blog, site or channel; its CEO or staff speaking about their own work; the paper's authors; the repository's owner; the court or regulator for its ruling). A repost counts by who WROTE it ("Repost: written by @<author>").
- `relay`: a near-bare relay of the maker's page or post: a link post, a reshare or a copy of the maker's text with no more than a line of its own (a Reddit or HN link to the official page, "X is out: <link>").
- `other`: anyone else: a news site, a channel retelling it in its own words, a commentator, a user. A third party's long retelling is `other` even if it links the official page.
- For `opinion_analysis`, `tutorial_explainer`, `community_post` and `other` with no outside happening, the author is the maker of their own post only if it is their own release; otherwise `other`.

## Hard cases (read before answering; these are the usual mistakes)
Type:
- **Unconfirmed:** an unsourced "BREAKING", an "EXCLUSIVE" from a third party, "is said to", "plans to", or the author's own inference ("judging by X's Instagram, Y is fundraising") is `leak_rumour`, not `business_event` or a release.
- **Argues vs reports:** if the title or opening is a claim or a judgement ("X is fake", "why X matters", "this is why the fee matters", "the quest for…"), the post is `opinion_analysis` even when it describes a policy, deal or product along the way. A commentator quoting another outlet and adding a view is `opinion_analysis`.
- **A person's remarks retold** ("a chip maker's CEO says superintelligence is 1-2 years away", a CEO profile, an interview) is `public_statement`, even with the channel's own comment.
- **Jokes, memes, quips, one-line takes** about anything are `opinion_analysis`. `other` is only for contentless or unclear posts, bare links, personal anecdotes, off-topic trivia, vlogs.
- **Selling or promoting** one's own book, paid video, course, talk, meetup, contest or newsletter signup is `promotion_event`. A newsletter ISSUE (its content: many items) is `digest`.
- **Explaining how something works** (a concept, an existing method, a technical note, a how-to) is `tutorial_explainer`, not `opinion_analysis` or `research_result`. New measured results are `research_result`.
- **A user's hands-on impressions** of a new model or product without measured numbers are `opinion_analysis`; with a measured benchmark, `research_result`. A personal project with nothing released (no repo, no download) is `community_post`.
- **Short reports from a channel** ("X is out", "X вышла", "X released Y") take the happening's type (`model_release`, `product_release`, ...), never `other`.
- **Off-topic** posts (politics, sport, history, celebrities, life; nothing about AI, tech, science or business) with no happening are `other`, even when they argue or joke.
- **Shows vs judges:** a post that SHOWS a personal demo, setup, experiment output or build ("I made X play a word game with Y") is `community_post`; a post that JUDGES a product or model ("X is so good", a review) is `opinion_analysis`.
- **A model update** (new checkpoint, new version of a model, weights or quantisations) is `model_release`; apps, APIs, tools and features are `product_release`.
- **A leaderboard or arena standing**, and a lab's own technical write-up of how it achieved a result, are `research_result`.
- **News retold mainly to speculate** about motives or consequences ("why did the lab pause? I think…") is `opinion_analysis`; news retold with a one-line comment keeps the happening's type.

Origin:
- **`maker` only when the author did the happening the post is about:** their own release, their own paper or experiment results, their company's announcement, their own event, book or course, their own newsletter issue. An author's own essay, opinion, joke, tutorial or community post is `other` (writing a post is not a happening).
- **Reposts count by who WROTE them:** "Repost: written by @<author>" — if the author is the maker (the company, its staff, the project), origin is `maker`, not `relay`.
- **A Hacker News or Reddit link post to the maker's own page**, with no text of its own (or only the page's text), is `relay`, not `maker`.
- A third party who retells or summarises the maker's news in its own words is `other`, not `relay`.

Rules: Russian and English are equal; always write headline_en, items and mentions in English. A very short post (a line and a link) still gets a reading: use the link's words if they say what it is. A `roundup` kind is always event_type `digest`.

**type_why** (write it BEFORE event_type): at most 15 words: what the post mainly does (reports / argues / teaches / asks or shows / promotes / lists / nothing) and which deciding rule or hard case settles the type.

Answer fields, exactly these names and in this order: kind, events, main ({headline_en, actors, object, action, date, numbers} or null), items, mentions ([{name, role}]), lang, type_why, event_type, origin.
