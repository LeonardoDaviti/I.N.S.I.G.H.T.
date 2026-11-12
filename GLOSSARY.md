# Glossary

The words INSIGHT's code and plans use for how posts get connected. Short on purpose; a term is added when it is
first needed, and its module is named where one owns it.

**Pairing** — the module that decides which pairs of posts (or of stories) may ever be compared, for each relation
(`backend/insight_core/markx/pairing.py`). Every candidate source and every gate before a judge lives behind it.

**Relation** — a question a judge may later be asked about a pair: *same story* (one story? the join, pair and
merge questions) or *connected* (a typed link between two stories). Each relation has one row in Pairing's policy
table.

**Gate** — one condition a pair must pass before it is judged: a window (how far apart in time), a cosine bar, an
entity-type list, a word count, a unit rule. Gates belong to a relation's policy row, never to a caller.

**Voice** — an independent source of a post. Two posts are independent voices when they come from different
sources and neither is a post the owner saved. A story's voices are its distinct sources.

**Happening** — what a post reports as a key: an action group (release, deal, funding, legal, people, pricing,
research, announcement), its parties, its stage, its stated day, its money amounts
(`backend/insight_core/markx/happening.py`). Two posts of one happening may be paired whatever their words or
language.

**Party** — an entity a happening is between: the thing released, the two companies in a deal, the company that
raised. Resolved to its root entity (or its name key until it is linked), never free text. Parties are unordered.

**Stage** — how far a happening has got, when the action says it: rumored, announced, released, closed. A later
stage of one happening is a development, not a new happening.

**Anchor** *(planned)* — what a follow-up attaches to: a Mark IX story, a Mark X story or a happening. Back in the
news and later developments will ask Pairing for follow-ups of an anchor, not only of a Mark IX story.

**Unit** *(planned)* — what is compared: a post, or one item (span) of a round-up. Today every unit is a whole post,
and a round-up is never compared as a whole.
