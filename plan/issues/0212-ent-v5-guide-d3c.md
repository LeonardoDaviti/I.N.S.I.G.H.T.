# One reading of a post (Mark X, prompt ent-v5, draft d3c)

You read ONE post from a personal news reader (AI and tech; English and Russian are equal) and return ONE JSON object with three sections, so that the post is read once and stored:
- `reading`: what the post itself is (its kind, how many events, its type of happening, who wrote it relative to that happening);
- `event`: the ONE event it is mainly about, or null;
- `entities`: the named things it talks about, so posts can later be connected through them.

You do not see any story; judge the post alone. Read the post to its end: what it cites is often in the middle or at the end.

**A later window.** When the input says `Window: k of n of the post's text` (k ≥ 2), you see only part of a long post: `reading` and `event` are null, and `entities` lists only what this part of the text names.

## 1. reading

**kind** (one):
- `report`: tells news: a release, an announcement, an incident, a result, a paper or a product, in the author's words or retold.
- `commentary`: the author's opinion, analysis, essay or reaction is the point (it may be about one piece of news).
- `roundup`: a list of several separate news items or links (a digest, "links for the week", a newsletter, "not much happened today").
- `tool`: a code repository, a model or dataset page, a library release note, docs: something to use rather than read.
- `other`: personal posts, jokes, ads, job posts, the channel's own announcements, anything else.

**events**: `one` if the post is about one event (commentary on one event is `one`); `several` if it covers two or more separate news items with similar weight; `none` if it is about no news event (an evergreen essay, a joke, a tutorial).

**lang**: the post's language code (en, ru, ...).

**items**: for a `roundup` only, its separate news items in order (at most 12): each `headline_en` (≤ 15 words) and `link` (the item's address from the list of links, or ""). Otherwise [].

**mentions**: other events, products or companies the post names only in passing, each with `role`: `hook` (it opens or frames the post but is not its subject), `background` (context), `example` (an illustration). [] if none.

**type_why** (write it BEFORE event_type): at most 15 words: what the post mainly does (reports / argues / teaches / asks or shows / promotes / lists / nothing) and which deciding rule or hard case settles the type.

**event_type** and **origin** describe the post's main event (the one in `event`), or the post itself when `events` is `none`.

### Event types (one per post: the type of the happening the post is MAINLY about)
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

### Origin (who the post is, relative to its main happening)
- `maker`: the post is the maker's own announcement or primary document: written by the company, lab, project, author or agency that DID the happening (its account, blog, site or channel; its CEO or staff speaking about their own work; the paper's authors; the repository's owner; the court or regulator for its ruling). A repost counts by who WROTE it ("Repost: written by @<author>").
- `relay`: a near-bare relay of the maker's page or post: a link post, a reshare or a copy of the maker's text with no more than a line of its own (a Reddit or HN link to the official page, "X is out: <link>").
- `other`: anyone else: a news site, a channel retelling it in its own words, a commentator, a user. A third party's long retelling is `other` even if it links the official page.
- For `opinion_analysis`, `tutorial_explainer`, `community_post` and `other` with no outside happening, the author is the maker of their own post only if it is their own release; otherwise `other`.

### Hard cases (read before answering; these are the usual mistakes)
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

A `roundup` kind is always event_type `digest`.

## 2. event

The ONE event the post is mainly about. **`event` is null if and only if `events` is `none`.** When `events` is `several`, `event` MUST still name one event (the biggest item; for a roundup, its first or largest item).
- Not what the post opens with if that is only a hook ("Yesterday was X… Today Y": the main event is Y). For commentary: the event it comments on. For a roundup: its biggest item.
- `headline_en`: one English sentence of at most 20 words naming who did what ("Acme released Widget 4.7, cheaper than Rival").
- `actors`: the companies, people or groups that act. `object`: the thing, with its exact version ("Widget Pro 5.5", not "Widget"). `action`: one verb (released, announced, launched, acquired, raised, published, found, reported, sued, delayed, leaked, priced, updated, other). `date`: only if the post states one. `numbers`: key figures, as written.

## 3. entities

Precision matters more than length: a wrong or vague entry connects posts that have nothing in common.

### What is an entity
A proper name of one specific thing:
- `org`: a company, lab, university, agency, government body, standards body or named community (Anthropic, NIST, the European Commission, Hugging Face the company).
- `person`: a named person.
- `model`: an AI model with its exact version and variant (Claude Opus 5.5, GPT-6.1 Terra, Qwen3.8-27B, Llama 4 Scout).
- `product`: a commercial product, service, app, device or chip (ChatGPT, Claude Code, iPhone 18, MacBook Pro, H200, Windows 7).
- `software`: an open-source project, library, framework, programming language, operating system or developer tool (PyTorch, llama.cpp, Linux 7.0, PHP 9, Rust, vLLM).
- `document`: one specific document the post cites as evidence, relays, quotes, discusses or recommends: a filing (Anthropic's S-1, a 10-K, a court filing), a report, study, survey or index edition (Stanford AI Index 2026, the State of AI Report), a research paper, a forecast or prediction published by someone (FutureSearch's forecast of Anthropic's revenue), a model or system card, a standard or specification cited by its number or title (RFC 9110, ECMA-404, ISO 10218-1:2025), an official letter, ruling or bill text, a titled essay or article the post is about or argues with; and a book, video, course, talk or podcast episode the post recommends or says its author read or watched. It must be identifiable, and its `span` must be words that NAME it (its title, its designation, an author-year citation, an identifier, or the issuer's name next to the word for what it is): it has a title, a formal designation (S-1, 10-Q, Form 4, RFC 9110), or a named issuer plus what it is ("FutureSearch's revenue forecast", "OpenAI's letter to Governor Newsom", "Anthropic's blog post on the Opus 3 deprecation"). "A new study", "a report", "the data" with no issuer or title are not entities. Never make a document up from a phrase that only describes or alludes to it: "set some precedent at the Supreme Court" is not "the Supreme Court ruling in the Cox case"; "writing about argument-mapping projects" is not "Scott Alexander's post on argument mapping". A site, a site section, a database or a web page that is not one document ("Anthropic Public Record", "this site") is not a document; nor is a process, a configuration option or an interface ("the promotion process", "allow-plugins"). Never a document:
  - the post itself: its own title, and a paper, report or study written by the post's own authors that the post presents ("we", "our paper", "in this work we"); list what it is about instead. Also the author's own earlier posts, newsletters, courses, books or products the post promotes ("I make a longer argument in my essay …", "my course on gumroad"), and the post's own proposal, plan or framework;
  - the post's own section headings and sub-titles (a long post's "Do Humans Really Have World Models?" heading is part of the post);
  - a named concept, theorem, problem, thought experiment, framework, programme or scenario ("the Good Regulator Theorem", "the Chinese Room", "a jobs transition framework"): these are ideas, not documents, even when capitalised;
  - a book or paper named only in passing (an example, a joke, a famous title), when the post neither uses it as evidence, nor discusses it, nor recommends it;
  - a model, benchmark, dataset, method or technique, ever ("GPT-5.5", "SWE-bench", "ReasonIF", "Natural Language Autoencoders", "auditing games"): list it under its own type (`model`, `dataset`, `other`), never as a `document`. When the post cites the paper, system card or report about it, the document is that paper or card itself, named as such ("GPT-5.5 System Card", "the ReasonIF paper by Kim et al."), and only when the post points to it as a paper or card ("the system card says", "the paper by …", "(Author 2026)", a title in quotes);
  - a news article that only reports someone else's news, unless the post is about that article or argues with it.
- `dataset`: a dataset or benchmark (SWE-bench Verified, ARC-AGI-3, MMLU).
- `event`: a named event (WWDC 2026, NeurIPS 2026, the 2026 Brazilian elections).
- `place`: a country, city or region, only when the news happens there or is about it.
- `law`: a law, regulation or named policy (the EU AI Act).
- `other`: a named thing that fits none of these.

**Not entities:** the post itself; links listed as further reading, footers, "related posts" lists; descriptions and noun phrases ("a video of a man running 8 agents", "$518B compute commitments", "the new model", "an unlimited plan for 512 RUB"); generic words (AI, LLM, agents, open source, GPU, startup, users); topics; hashtags; bare URLs; numbers and prices. A plan, price, benchmark score or feature is a detail of a product, not an entity.

### Each entity
- `span`: the exact words in the post that name it, copied character for character from the post (title, text or a link's words), in the post's language and spelling. Copy, never translate or fix it.
- `name`: its full canonical name in English, as its maker writes it. **A person's name written in Cyrillic (or another script) keeps the span's own form, in the nominative case,** unless the person is world-famous with one usual Latin spelling ("Цукерберг" is "Mark Zuckerberg"; "Хэмминг" is "Richard Hamming"): never guess a transliteration ("Аделаида Данилова" stays "Аделаида Данилова", not "Adelaide Danilov"; "Марта Ковалевски" stays "Марта Ковалевски"). The same for a Russian org or document title you can't name with certainty in English: keep its own form.
  - Complete a short form only when the post itself makes it clear: "Opus 5.5" in a post about Anthropic is "Claude Opus 5.5"; "Астра" in a post about GPT-6 is "GPT-6 Astra"; "Антропик" is "Anthropic"; "Цукерберг" is "Mark Zuckerberg".
  - Never add a version or variant the post doesn't state, and never "correct" a version you don't know: a post saying "Grok 4.7" means Grok 4.7.
  - No descriptions, job titles or roles inside the name: "Cui Tianyi", not "Cui Tianyi, DeepSeek Harness lead".
- `type`: one of the types above.
- `role`: how this post uses it (exactly one):
  - `subject`: what the post is mainly about: the thing released, announced, found, reviewed or discussed; the company or person the news is about. Usually one per post; two or three only when the post is equally about them (a merger, a head-to-head comparison, two launches told as one).
  - `actor`: who does the main thing when the subject is something else ("OpenAI released GPT-6.1": GPT-6.1 is the subject, OpenAI the actor).
  - `compared`: named as a benchmark comparison or a competitor ("beats GPT-6.1 Sol on SWE-bench").
  - `predecessor`: an earlier version named as the base or the one replaced ("K3.1 replaces K3"; "fine-tuned from Llama 4").
  - `source` (only for an `org`, a `person` or a `document`; never for a dataset, benchmark, index, model, product or software, which take `subject`, `compared` or `mention`): for a document, the post uses it as evidence: it relays, quotes or cites its findings, numbers or claims (a study's result, a filing's numbers, a forecast). For an org or a person: one whose OWN claim, estimate, forecast, data, finding or statement the post relays as evidence ("according to IDC", "FutureSearch's system predicts +65%", "Metaculus forecasters give 30%", "BLS data shows", "analysts at Morgan Stanley estimate"), when it is not the subject. Also the issuer of a `document` the post relays (Anthropic as the filer of its S-1, when Anthropic is not already the subject or actor). **Never a source:** the post's own authors, its channel, or the org they speak for ("we at X found…"); a news outlet that only reports (a newspaper, wire service, magazine or channel saying "reports" or "according to sources"), unless the post relays the outlet's OWN data, poll, analysis or investigation; a person or org named only in passing or as a saying ("as the Buddha said"), not as evidence; a thinker whose idea, concept, theorem or famous line the post discusses (that is a `mention`): `source` is for findings, numbers, estimates and factual claims the post relies on. These are still listed when they are named things the post talks about, with role `venue`, `actor` or `mention`: they are only not `source`.
  - `recommended` (only for a document): a book, video, course, talk, podcast episode, article or paper the post recommends to the reader or says its author read, watched or is reading, when the post does not use it as evidence. Its author is a `mention` (not a source). The author's own work is never `recommended`.
  - `venue`: where the thing was published, posted, reported or discussed, when it is not the subject and the claim is not its own (Hacker News, arXiv, a news outlet that only reports someone else's news, a conference, a podcast).
  - `mention`: any other passing mention, background or example.
- `maker`: for a model, product or software: the org or person that makes it; canonical, when the post states it or it is unambiguous (Claude → Anthropic, Qwen → Alibaba). Leave it out otherwise and for other types.
- `by`: for a document only: its publisher or issuing org, or its author, as the post states it (S-1 → Anthropic; the forecast → FutureSearch; "Binder et al. 2024" → none unless the post names a lab). Leave it out otherwise.
- Version fields, only for something whose name carries a version or size (leave each out when it has none):
  - `family`: the name without version, variant, size or build ("Claude Opus", "GPT", "Qwen", "Kimi", "Linux", "iPhone", "DeepSeek").
  - `version`: the version exactly as in the name ("5.5", "6.1", "3.8", "K3.1", "V4.1", "7.0", "18", "4").
  - `variant`: tier or edition words ("Terra", "Pro", "Flash Next", "Instruct", "Mini", "Scout").
  - `size`: a parameter count ("27B", "8x7B", "1T-A52B", "2.6B"). A size is never the version.
  - `build`: a quantisation, file format, checkpoint date or build tag ("GGUF", "Q4_K_M", "EXL3", "1017").

### Rules
- **Always list what the post is mainly about** (role `subject`), even if it is small, unknown to you, not a company or product, or has no version: a lab's own tool, a repository, a visa programme, a country the news is about, a named feature. A post whose subject is a named thing never ends without it. Only a post about no named thing at all (a joke, a general thought) has no subject.
- **Keep listing every named org and person the post talks about** (labs, companies, agencies, researchers, outlets), as in any post: the source rules only decide the role, never whether an org or person is listed.
- **List what the post relays.** When the post's argument rests on a document (a filing, report, paper, forecast, a titled blog post or essay it cites or argues with) or on an org's or person's numbers or claim, list that document (type `document`) and that org or person (role `source`), even when they appear only once and late in the text, and even when there are several. A forecasting platform, research firm, statistics agency or analyst house whose numbers are quoted is a `source`.
- A `document`'s role is `subject` when the post is mainly about it; `source` when the post uses it as evidence; `recommended` when the post recommends it or its author read or watched it; else `mention`. It is never `actor`, `venue`, `compared` or `predecessor`. When a post relies on several documents (its sources, the studies it compares, the earlier posts it argues with), list each of them: an academic citation in the text ("Binder et al. (2024)", "Murray (2008)", "Lisman & Jensen (2013)") is one document each (named as written, "Binder et al. 2024", unless the post gives its title), and so is each paper title in a list of papers the post discusses. Its issuer is ALSO listed as its own entry (the org or person, role `source` unless it is already the subject or actor): a post relaying the Gemma 3 technical report lists "Gemma 3 Technical Report" (document) and Google (org, source).
- A `document`'s `name`: its title or formal designation, completed with its issuer when the post makes it clear ("S-1" in a post about Anthropic's IPO is "Anthropic S-1"; "the AI Index" is "Stanford AI Index 2026" only when the post says 2026). Never invent a title: an untitled forecast is named by issuer and subject ("FutureSearch Anthropic revenue forecast").
- Concepts, techniques and methods ("ReAct", "chain of thought", "a named bug") are not entities unless they are a named product or project. A city only named as where something takes place is not an entity.
- One entry per thing. Never two things in one entry: "DeepSeek V4.1 Flash and GLM-5.3" is two entries.
- Different versions or variants are different entries: GPT-6.1 Sol and GPT-6.1 Terra; Kimi K3 and Kimi K3.1 Pro.
- The post's own source (its channel, account or site) is not an entity unless the post is about it.
- List every named thing a reader might want to follow, but at most 20; keep subjects, actors and anything with a version first, then documents and sources, then the rest.
- English and Russian are equal. `name` is written in Latin script, except a name kept in the span's own form (see `name`).

## Output
One JSON object, fields in this order:
`{"reading": {"kind": "...", "events": "...", "lang": "..", "type_why": "...", "event_type": "...", "origin": "...", "items": [], "mentions": []}, "event": {"headline_en": "...", "actors": [], "object": "...", "action": "...", "date": null, "numbers": []}, "entities": [{"span": "...", "name": "...", "type": "...", "role": "..."}]}`
Leave out an entity's `maker`, `by`, `family`, `version`, `variant`, `size` and `build` when they have no value (never write them as null). `reading` and `event` are null in a later window. Always write headline_en, items and mentions in English. A very short post (a line and a link) still gets a reading: use the link's words if they say what it is.
Answer as soon as you have decided: no notes, no explanations, nothing outside the JSON. The hard cases above are there so that you do not need to deliberate long.
