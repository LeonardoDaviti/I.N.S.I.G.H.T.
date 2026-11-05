# Judge guide (Mark X F0.5, prompt v1): how does this post relate to this story?

You see a STORY (an English headline, its event slots and a short summary, built from its reports) and one POST (its title, its text, and the reading of the post). Decide the post's relation to the story's event. The owner's rule C: a post is in a story only if that event is the post's MAIN subject; touching the topic is not enough.

Relations (pick one):
- `same_event`: the post reports or retells this event (any language, any words).
- `development`: a follow-up of this event: a status update, "services restored", the open weights after the preview, an explainer or fact-check of it, the next step of the same story.
- `reaction`: commentary, opinion or a one-line reaction whose subject is this event.
- `mention`: the post is mainly about something else; this event is a hook in its opening, a link in passing, background or an example.
- `digest_item`: the post is a roundup or digest and this event is one of its items.
- `different`: another event, even if it shares the topic, the company, the product family, the author or the week (another model's release; another piece of news from the same company; a competitor's answer is `different` unless the post is mainly about this event).
- `cant_tell`: the post has too little text to say (a bare link with no words).

Notes:
- Versions matter: "Grok 4.7" and "Opus 5.5" are different events; "GPT-6" and "GPT-6 Astra" may be the same family but check the action.
- A post about two events equally is `same_event` (or `reaction`) for each of them.
- The same company or the same week is never enough.
- Russian and English are equal; judge the meaning.

Answer with JSON: {"relation": one of the seven, "confidence": 0-100 (how sure you are of this relation), "reason": one short English sentence}.
