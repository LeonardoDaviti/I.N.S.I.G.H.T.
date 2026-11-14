# Story significance guide (Mark X News, prompt significance-v1)

You see one news story from a reader's News: its headline, what INSIGHT already measured about it (the kind of happening, its main subjects and their kind, how many sources covered it and how deeply, the kinds of pages its posts link) and its member posts from different sources (English and Russian), each with its platform, source, date, length, title and the start of its text. Judge how significant the event is for people who work in its field, whatever its loudness. A story many sources repeat can matter little; a story two expert sources take apart can matter a lot.

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
- `effect`: how big its effect is on the work of people in its field, 1 to 5:
  - 5: changes how many practitioners work now (a new default, a large leap in what is possible, a widely used tool replaced);
  - 4: a substantial improvement many practitioners can adopt (much faster, cheaper or better at a common task, available to use);
  - 3: useful to a part of the field, or a notable step whose effect is not yet clear;
  - 2: small, incremental, or interesting but with little practical effect;
  - 1: no effect on anyone's work (gossip, a minor business note, a repeat of old news, an opinion with nothing new).
  Judge the effect of the event itself, not how loudly it is covered, how famous its maker is, or how many sources repeat it. A large company's minor feature is 2; an unknown team's method that makes a common algorithm ten times faster and ships in a widely used library is 4 or 5.
- `scope`: who it touches: `field_wide` (most people in the field), `subfield` (one area of it), `niche` (a few specialists or one product's users).
- `why`: one English sentence, at most 30 words, naming the concrete fact that decided `effect` (a figure, where it shipped, what it replaces).

Return JSON only: {"event": "...", "usable": "...", "shipped_in": null, "adoption": [], "coverage": "...", "effect": 3, "scope": "...", "why": "..."}
