# What this post cites (Mark X F7, prompt ent-v4.2 cite)

You read ONE post from a personal news reader (AI and tech; English and Russian are equal). Another pass already lists the post's products, models, companies and people. Your only job: list **everything the post cites or relays**, so that posts can later be connected through the same paper, report, filing or source. Read the post to its very end, every paragraph and every reference list: the citations are often in the middle, at the end, or packed many to a sentence. A dense post may cite 20 or 30 things; list each one. Nothing else.

## List exactly two kinds of things

### 1. Documents (`type` `document`)
One specific document the post cites as evidence, relays, quotes, discusses or argues with, or recommends:
- a research paper, preprint, study, survey, poll, experiment's write-up, meta-analysis;
- a report, index edition, white paper, forecast or prediction published by someone, a dataset's paper;
- a filing (S-1, 10-K, a court filing, a motion, a brief, a ruling, an opinion), a bill's text, an official letter, an inspector-general or agency report;
- a model card or system card;
- a standard or specification cited by its number or title (RFC 9110, ECMA-404, ISO 10218-1:2025, a NIST SP);
- a titled essay, blog post or article the post is about or argues with;
- a book, video, course, talk or podcast episode the post recommends, or says its author read or watched.

A book, essay or article named only as an example, an allusion, a famous title or one item in a list of things the author mentions is NOT a document: list it only when the post takes a finding, number, argument or quote from it, discusses it at some length, or explicitly recommends it.

**An academic citation is always ONE `document`, never a person or an org:** "Bosch et al. (2025)", "Tian et al.", "Shannon & Nicolaides", "(Parvin, 2019)" are each a document named as written with its year ("Bosch et al. 2025"); never list "Bosch et al." or its authors as a `person` or `org` source.

It must be identifiable, and its `span` must be words that NAME it: its title, its designation ("RFC 9110", "Form 10-K"), an academic citation ("Binder et al. (2024)", "Murray (2008)", "Lisman & Jensen, 2013", one entry each), an identifier ("arXiv:2401.01234", a DOI), or the issuer's name with what it is ("the DoD Inspector General's report", "METR's time-horizon paper", "FutureSearch's revenue forecast"). A link's words count as a span when they give a title ("Measuring AI Ability to Complete Long Tasks").

Ask of each document: does the post take a finding, number, claim or quote from it, or build its argument on it? If the post only names it, gives it as an example of a genre, or lists it among other titles, leave it out.

`role`: `source` when the post uses it as evidence (relays its findings, numbers or claims), and also for a paper or report the post explains or builds on; `recommended` ONLY when the post explicitly recommends it to the reader ("read this", "worth watching", "I recommend") or says its author read or watched it, and does not use it as evidence; `subject` when the post is mainly about this one document (a post reviewing a paper). A document's `span` is never a description of what it says ("analyzes American class", "the current state of the debate"): it is the document's title, designation, citation, link or issuer + kind.

### 2. Sources (`type` `org` or `person`, role `source`)
An organisation or person whose OWN claim, estimate, forecast, data, finding, analysis or statement the post relays as evidence ("according to IDC", "METR measured…", "Epoch AI estimates", "analysts at Morgan Stanley", "the BLS reported", "CRS notes", "researchers at Bocconi found"), and the issuer or author of each document you list as evidence (a lab, agency, think tank, company, journal's authors when named as a group).

## Never list
- Products, models, software, libraries, tools, repositories, datasets, benchmarks, leaderboards, arenas, attacks, methods, techniques, concepts, theorems, events, places, laws as such: they are not documents, even when they come from a paper ("Delphi", "GCG", "Gemma Scope", "Steering Arena" are not documents). A model or benchmark's name is never a document ("GPT-5.5", "SWE-bench"); its system card or paper is, when the post points to it as a card or paper ("the GPT-5.5 system card says").
- The post itself: its own title, its section headings, a paper or report by the post's own authors that the post presents ("we", "our paper", "in this work"), the author's own earlier posts, newsletters, courses, books or products it promotes.
- A description instead of a name: "a new study", "a report", "the data", "the Supreme Court" doing something, "writing about X" — unless the post gives a title, a designation, an author-year citation or a named issuer next to what it is. Never make a title up.
- A site, a site section, a database, a home page, a process or a configuration option.
- A news outlet that only reports someone else's news (a newspaper, wire service or channel saying "reports"), unless the post relays the outlet's OWN data, poll, analysis or investigation.
- An org or person named as an example, in a list, as a place someone studied or works, or as the post's subject doing something: only those whose own findings or data the post relays.
- A person or org named in passing, as a saying or an example, or a thinker whose idea or famous line the post discusses: only those whose claim or data the post relies on as evidence.
- The post's own authors, its channel, or the org they speak for.
- Links in a footer, a "further reading" or "related posts" list, share or subscribe links.

## Each entry
- `span`: the exact words in the post that name it, copied character for character (title, text, or a link's words), in the post's language. Never translate or fix.
- `name`: its canonical name in English. A document: its title, or its designation completed with its issuer when the post makes it clear ("Anthropic S-1"), or an academic citation as written ("Binder et al. 2024"), or issuer + what it is ("DoD Inspector General report on …" only with words from the post). A person's name written in Cyrillic keeps the span's own form in the nominative case unless the person is world-famous with one usual Latin spelling; never guess a transliteration.
- `type`: `document`, `org` or `person`.
- `role`: for a document `source`, `recommended` or `subject`; for an org or person always `source`.
- `by`: for a document, its publisher, issuer or author as the post states it, else null; null for an org or person.

One entry per thing; never two things in one entry. At most 30 entries; when a post cites more, keep those the post uses most. Many posts cite nothing: an empty list is fine.

## Output
One JSON object: `{"id": "<id>", "entities": [{"span": "...", "name": "...", "type": "document" | "org" | "person", "role": "source" | "recommended" | "subject", "by": null}]}`.
