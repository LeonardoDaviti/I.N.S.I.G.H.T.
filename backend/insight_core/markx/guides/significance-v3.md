# Story significance guide (Mark X News, prompt significance-v3)

You see one news story from a reader's News: its headline, what INSIGHT already measured about it (the kind of happening, its main subjects and their kind, how many sources covered it and how deeply, the kinds of pages its posts link) and its member posts from different sources (English and Russian), each with its platform, source, date, length, title and the start of its text. Judge how significant the event is for people who work in its field or follow it closely, whatever its loudness. An event matters in two ways, and either can make it significant: what it changes in what the field knows or can do (a new capability shown, an open problem solved, a new state of the art, a first of its kind), and what people can use or build with today. A result nobody can use yet can matter as much as a release. A story many sources repeat can matter little; a story two expert sources take apart can matter a lot.

Answer these, from the posts only (never from what you know elsewhere; a claim the posts only report is still the event they report):

- `event`: what kind of event it is, the closest of:
  - `new_method`: a new technique, algorithm or approach (often with a paper) that changes how something is done;
  - `new_model`: a new model or a new version of one (weights, an API, a checkpoint);
  - `new_tool`: a new library, framework, app, dataset or developer tool, or a new open project;
  - `release_update`: a new version or feature of an existing product, tool or library;
  - `research_result`: a finding, measurement, study or paper that is not a method one can apply;
  - `benchmark`: a benchmark, leaderboard or evaluation, or a new result on one;
  - `product_launch`: a consumer or business product launched or shown (not a tool for practitioners);
  - `deal_funding`: an acquisition, investment, funding round, IPO, partnership or revenue figure;
  - `policy_legal`: a law, regulation, lawsuit, ruling or government action;
  - `security_incident`: a vulnerability, attack, leak of data or abuse;
  - `outage`: a service down or degraded;
  - `people`: someone hired, leaving, appointed, or an organisation's people news;
  - `opinion_analysis`: an essay, opinion, interview or analysis with no new event;
  - `tutorial`: a guide, explainer or how-to;
  - `other`.
- `usable`: can people in the field use it or build with it: `now` (it is out: code, weights, an API, a package, a product they can use), `soon` (announced with a date, or a waitlist), `no` (nothing to use: news about a company, a law, a person, an opinion, a result without anything released).
- `shipped_in`: where it is available, in at most 8 words, as the posts state it ("in a widely used open-source library", "as open weights", "in the company's API"); null when nowhere or not stated.
- `adoption`: every signal the posts give, of: `widely_used_library` (it landed inside a library or tool many practitioners already use), `open_code` (its code is public), `open_weights`, `api`, `paper` (a paper or preprint describes it), `paper_with_code` (a paper and its code), `official` (the maker announced it itself), `benchmark_result` (it beats or sets a measured result). An empty list when none.
- `coverage`: how deeply the posts cover it: `expert_breakdown` (at least one post explains how it works or why it matters in detail: a method's steps, a model's architecture, measured trade-offs), `reports` (posts report the event with its facts), `passing_mentions` (a line in a digest, a link with a few words, reactions).
- `breakdowns`: the numbers of the posts shown (`[1]`, `[2]` ...) that are an expert breakdown in their own right: the author's own explanation of how the thing works or why it matters, in detail and with specifics (its method, architecture, design choices, measured trade-offs, numbers it reasons about). Not a breakdown: a report of the announcement (even a long one), the maker's own announcement or a copy of it, a list of links or headlines, a short reaction or opinion, a how-to unrelated to the event. An empty list when none. Example: `[2]`.
- `effect`: how much it changes the field, 1 to 5, by what it shows is possible or by what people can now do, whichever is larger:
  - 5: changes the field now: a large leap in what is possible (a long-open problem solved, a capability no system had, a far better state of the art on a task that matters), or a new default many practitioners switch to, or a widely used tool replaced;
  - 4: a clear advance: a first of its kind, a new state of the art or a marked jump on a measured task, a result experts in the field treat as notable, or a substantial improvement many practitioners can adopt (much faster, cheaper or better at a common task, available to use);
  - 3: useful to a part of the field, a solid step on a known problem, or a notable result whose effect is not yet clear;
  - 2: small or incremental: a minor feature, a small gain, a measurement that confirms what was expected, a curiosity;
  - 1: no effect on what the field knows or can do (gossip, a business or funding note, a person's news, a repeat of old news, an opinion with nothing new).
  A result is judged by what it shows, as the posts report it, not by whether a tool came with it: "nothing released yet" never lowers a result's effect (that is `usable`'s answer). Business events (funding, deals, revenue, valuations, hires, departures), lawsuits and opinion stay 1 or 2 unless the posts show they change what practitioners can do or use (a widely used service shut, a rule that forbids a common practice: 3 or more). A claim of a result stated only by its maker is still the result; a result the posts show others doubting or failing to reproduce is lower.
  Judge the effect of the event itself, not how loudly it is covered, how famous its maker is, or how many sources repeat it. A large company's minor feature is 2; an unknown team's method that makes a common algorithm ten times faster and ships in a widely used library is 4 or 5; a system shown solving problems experts had not solved is 4 or 5 even with nothing to download.
- `scope`: who it touches: `field_wide` (most people in the field), `subfield` (one area of it), `niche` (a few specialists or one product's users).
- `why`: one English sentence, at most 30 words, naming the concrete fact that decided `effect` (a figure, what it showed or solved, where it shipped, what it replaces).

Return JSON only: {"event": "...", "usable": "...", "shipped_in": null, "adoption": [], "coverage": "...", "breakdowns": [], "effect": 3, "scope": "...", "why": "..."}
