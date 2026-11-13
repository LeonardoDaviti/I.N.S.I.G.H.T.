# Glossary

The words INSIGHT's code and plans use for how posts get connected. Short on purpose; a term is added when it is
first needed, and its module is named where one owns it.

**Pairing** — the module that decides which pairs of posts (or of stories) may ever be compared, for each relation
(`backend/insight_core/markx/pairing.py`). Every candidate source and every gate before a judge lives behind it.

**Relation** — a question a judge may later be asked about a pair: *same story* (one story? the join, pair and
merge questions), *connected* (a typed link between two stories), *develops* (a later post follows up an
anchor) or *attach* (a round-up's item carries a stored post: a digest item, never a voice). Each relation has one
row in Pairing's policy table.

**Gate** — one condition a pair must pass before it is judged: a window (how far apart in time), a cosine bar, an
entity-type list, a word count, a unit rule. Gates belong to a relation's policy row, never to a caller.

**Voice** — an independent source of a post. Two posts are independent voices when they come from different
sources and neither is a post the owner saved. A story's voices are its distinct sources.

**Byline** — who wrote a post, via whom: its original author when its feed did not write it (an X repost or quote's
account, a Telegram forward's channel), the feed that carried it, and the account it quotes
(`backend/insight_core/utils/byline.py`; the screens' one formatter `frontend/src/lib/byline.ts`). Display only: a
post's voice is Pairing's to decide, and a repost counts as its author's voice only when a source follows that author.

**Happening** — what a post reports as a key: an action group (release, deal, funding, legal, people, pricing,
research, announcement), its parties, its stage, its stated day, its money amounts
(`backend/insight_core/markx/happening.py`). Two posts of one happening may be paired whatever their words or
language.

**Event type** — what kind of happening a post reports, whichever read guide said it: a closed type (and who tells
it), and the happening group of its main action. Read only through the event-type seam
(`backend/insight_core/markx/event_types.py`), never from a reading's raw fields. A post's happening key is stored
(`mx_happenings`) with the inputs it was computed from, and computed again when they move.

**Party** — an entity a happening is between: the thing released, the two companies in a deal, the company that
raised. Resolved to its root entity (or its name key until it is linked), never free text. Parties are unordered.

**Stage** — how far a happening has got, when the action says it: rumored, announced, released, closed. A later
stage of one happening is a development, not a new happening.

**Anchor** — what a follow-up attaches to: a Mark IX story, a Mark X story or a happening no story holds
(`backend/insight_core/markx/anchors.py`). Back in the news and later developments ask Pairing's *develops* relation
for an anchor's follow-ups: its happening first, its subject second. In Shadow beside the old engines (0180).

**Round-up** — a post that carries many separate items: a daily digest, a link list, a long newsletter. Its reading
says so, or it has a digest's shape and its source's posts mostly have it (`backend/insight_core/markx/units.py`). A
round-up its reading names is never compared as a whole; its items (units) are never voices. Its time is its issue's: its latest attached item's (Pairing's
post date); its own dates are never rewritten.

**Unit** — what is compared: a post, or one item (span) of a round-up: (post, n, span, links, text, at), stored
(`mx_units`). A unit is attached (Pairing's *attach* relation) to the stored post it links and the story holding it,
as a digest item: the story shows "also in round-ups", and the own round-up (the digest) counts its curators. The
worker gives each unit a type (the event types, with `promo`), a short headline and whether it only continues the
unit before; an own round-up keeps the news types. A unit is never a voice, a member, a mention or a News count.
