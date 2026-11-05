# Judge guide for two stories (Mark X F2 merges, prompt v1)

You see STORY A and STORY B, each shown by its card (an English headline and the event's slots) and up to three of its members (posts from different sources). Decide how STORY B's event relates to STORY A's event. The owner's rule C applies to stories too: they are the same story only if they are about the same event.

Relations (pick one):
- `same_event`: A and B report the same event (the same release, announcement, incident or result), in any language or framing. Two parts of one event are the same event (the release and its open weights on the same day; the leak of a CVE and its fix release, if they are one security release).
- `development`: B is a follow-up of A's event (a status update, the open weights weeks after the preview, an explainer, a fix after an incident).
- `reaction`: B is commentary whose main subject is A's event.
- `mention`, `digest_item`: B is mainly about something else, or B is a roundup that lists A's event.
- `different`: another event, even with the same company, product family, topic or week.
- `cant_tell`: too little text.

Versions matter ("Grok 4.7" and "Opus 5.5" are different events). Russian and English are equal.

Answer with JSON: {"relation": one of the seven, "confidence": 0-100, "reason": one short English sentence}.
