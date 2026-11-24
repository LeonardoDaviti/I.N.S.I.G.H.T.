# Judge guide for two stories (Mark X merges, prompt judge-story-v2)

A news reader shows one row per event. You see STORY A and STORY B, each shown by its card (an English headline, the event's slots, a summary) and up to three of its members (posts from different sources). Decide whether the two are one row (`same_event`) or how B relates to A otherwise. `same_event` joins them into one story; every other answer keeps them apart.

## One release is one row
Everything about ONE release of one exact thing (one version of a model, one product, one feature launch) is `same_event`, whatever stage each story reports and however it frames it:
- before it: a rumour, a leak, a teaser, a report that it is coming next week, a preview or waitlist;
- the release itself: the launch, its open weights, its availability on more platforms, plans or countries in the days around it (an API, an app, a cloud, general availability after a preview of the same version), its price, and the maker's own builds of it (GGUF or quantised weights the maker itself publishes);
- right after it: its benchmark results and rankings by anyone ("X 3 tops leaderboard Y", "X 3 ranks #1"), the maker's own details (system card, report, safeguards shipped with it, its demos), people trying it (first impressions, reviews, praise, complaints, experts checking its claims).
Sibling things a maker announces as one launch (a family's sizes or variants named in one announcement, two models released together) are one release: a story about one of them and a story about the launch are `same_event`.

Not one release:
- two versions or two variants launched separately, even by one maker days apart (X 3 and X 3.1; a Flash model and a Pro model released on different days; open weights of a different size released on its own day): `different`;
- a later revision or update of a thing already out (a safeguards change weeks later after a backlash, a price cut later, a reversal): `development`;
- a result achieved WITH the thing (a problem it solved, a proof, a discovery made with it, even announced on the launch day): its own event, so `different` from the release; two reports of that same result are `same_event`;
- a project someone else built with it (an app, a game, a site), or another party's fine-tune, distillation or own quantised weights of it: `different`;
- a leaderboard or benchmark launch about many models where the thing is one entry: `different`.

## Other events
- The same happening reported twice, from two sides or in two framings, is `same_event`: a regulator lifting a restriction and the maker restoring access that day; an incident and the company's own account or postmortem of that incident; a filing and the reports of that filing; the same investigation, deal, lawsuit, statement or study described by different sources.
- Each step of a saga is its own row: a report that something is being prepared and the thing done (a board preparing to remove a CEO, then the CEO resigning), a resignation and a later petition or a later "would return", an IPO filing, its roadshow and its pricing, a lawsuit filed after the incident it is about, an investigation opened and its outcome. B is `development` (or `reaction` for a party's public response to A).

## Relations (pick one)
- `same_event`: one row, as above.
- `development`: B is a later, distinct step that follows A's event (a saga's next step, a later revision or update).
- `reaction`: B is a named party's public response to A's event that is itself news (a government's or rival's answer, a petition, a protest). Reviews and people trying a release are not a reaction: they are its `same_event`.
- `mention`, `digest_item`: B is mainly about something else, or a roundup that lists A's event.
- `different`: another event, even with the same company, product family, topic or week. Stories that share one roundup post or one aggregator post but have different main subjects are `different`.
- `cant_tell`: too little text.

## How
- Judge the main subject of each story (its headline and card first), not the posts the two share.
- Versions matter: "X 4.7" and "X 5.5" are different releases. Russian and English are equal.
- `confidence` is how sure you are of the relation you pick: when both stories name the same exact thing and the same release or happening, `same_event` is 90 or more.
- Write `reason` first: one short English sentence naming what decides it.

Answer with JSON: {"reason": one short English sentence, "relation": one of the seven, "confidence": 0-100}.
