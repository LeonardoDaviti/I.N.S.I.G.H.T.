# Glossary

The words INSIGHT's code and plans use for how posts get connected. Short on purpose; a term is added when it is
first needed, and its module is named where one owns it.

**Pairing** — the module that decides which pairs of posts (or of stories) may ever be compared, for each relation
(`backend/insight_core/markx/pairing.py`). Every candidate source and every gate before a judge lives behind it.

**Post date** — which time of a post a query reads, one of four, all Pairing's (never an inline `COALESCE`): the
*post date* (Mark X's time: a round-up's issue time, else its own date), the *ordinary date* (its own: surfaced, else
published, else fetched: the feed, the planners, a task's input), the *published date* (0128's order of a story's
lines) and *Mark IX's time* (published, else fetched).

**Relation** — a question a judge may later be asked about a pair: *same story* (one story? the join, pair and
merge questions), *connected* (a typed link between two stories), *develops* (a later post follows up an
anchor) or *attach* (a round-up's item carries a stored post: a digest item, never a voice). Each relation has one
row in Pairing's policy table.

**Gate** — one condition a pair must pass before it is judged: a window (how far apart in time), a cosine bar, an
entity-type list, a word count, a unit rule. Gates belong to a relation's policy row, never to a caller.

**Voice** — an independent source of a post: who a post counts as, and how many voices posts are
(`backend/insight_core/utils/voice.py`: `voice_of(post, policy)`, `count(posts, policy)`; the key forms are the
module's own). A post the owner saved is never a voice. The two engines still count by different rules, each a named
**voice policy**: Mark X's (`MARKX`: a voice is a source, or the followed source a repost's author is) and Mark IX's
(`STORIES_IX`: a website's publication, a Reddit poster, else the source, a confirmed voice's channels one, copies of
one text one, a tweet's reposters and author's source voices beside the post's own; `NEWS_IX`: every owner's
channels one).

**Byline** — who wrote a post, via whom: its original author when its feed did not write it (an X repost or quote's
account, a Telegram forward's channel), the feed that carried it, and the account it quotes
(`backend/insight_core/utils/byline.py`; the screens' one formatter `frontend/src/lib/byline.ts`). It holds every
"who wrote it" question the modules ask: the author's account, whether a row is a repost, Nitter's one "RT by @"
pattern. Which voice that makes is Voice's: a repost counts as its author's voice only when a source follows that
author.

**Happening** — what a post reports as a key: an action group (release, deal, funding, legal, people, pricing,
research, announcement), its parties, its stage, its stated day, its money amounts
(`backend/insight_core/markx/happening.py`). Two posts of one happening may be paired whatever their words or
language.

**Event type** — what kind of happening a post reports, whichever read guide said it: a closed type (and who tells
it), and the happening group of its main action. Read only through the event-type seam
(`backend/insight_core/markx/event_types.py`), never from a reading's raw fields; the type lists (News types, leak,
announced, a unit's news types) are made there from the closed types. A post's happening key is stored
(`mx_happenings`) with the inputs it was computed from, and computed again when they move.

**Party** — an entity a happening is between: the thing released, the two companies in a deal, the company that
raised. Resolved to its root entity (or its name key until it is linked), never free text. Parties are unordered.

**Stage** — how far a happening has got, when the action says it: rumored, announced, released, closed. A later
stage of one happening is a development, not a new happening.

**Anchor** — what a follow-up attaches to: a Mark IX story, a Mark X story or a happening no story holds
(`backend/insight_core/markx/anchors.py`). Back in the news and later developments ask Pairing's *develops* relation
for an anchor's follow-ups: its happening first, its subject second. In Shadow beside the old engines (0180).

**Round-up** — a post that carries many separate items: a daily digest, a link list, a long newsletter. Its reading
says so, or it has a digest's shape and its source's posts mostly have it (`backend/insight_core/markx/units.py`:
`roundup_sql`, which Discover reads too). A
round-up its reading names is never compared as a whole; its items (units) are never voices. Its time is its issue's: its latest attached item's (Pairing's
post date); its own dates are never rewritten.

**Unit** — what is compared: a post, or one item (span) of a round-up: (post, n, span, links, text, at), stored
(`mx_units`). A unit is attached (Pairing's *attach* relation) to the stored post it links and the story holding it,
as a digest item: the story shows "also in round-ups", and the own round-up (the digest) counts its curators. The
worker gives each unit a type (the event types, with `promo`), a short headline and whether it only continues the
unit before; an own round-up keeps the news types. A unit is never a voice, a member, a mention or a News count.

**Switched off** — a source the owner turned off (`sources.enabled` false). It is not fetched, and it never feeds a
suggestion: its posts are no evidence for Discover, a track's Discover and source suggestions, the scout, the main
source missing rows or the voices' suggestions, and its address is never proposed (it stays followed). Its stored
posts keep their places, and their voices, in News, stories and Classics. One rule:
`backend/insight_core/db/repo_stories.py` (`suggestable_sql`, `switched_off`, `SourceFacts.suggestable`) (0200).

**Identity facts** *(0184, built v10.18 behind a switch)* — what an entity is, as one sense of its name: its kind,
its maker, a one-line "what it is", the few words that tell it from another thing of the same name, and whether the
name is only a generic word (`markx/entity_facts.py`, `mx_entity_facts`). Linking a bare name asks them; the
timeline, cards and search read them (`entity_facts.read`, by id), never re-deriving a maker or a kind.

**Sense** *(0184)* — one thing a name stands for. A bare name ("Vexa") may have several senses, each its own entity
with its own identity facts; a mention is placed in one sense (a pin `by` facts), never joined by the name alone.

**Official channel** *(0196, built v10.18; Shadow by default)* — an actor's own stream of announcements (its blog or newsroom section, its
releases feed, its X or Telegram account), proven by code: owned by the actor, a dated stream, carrying its
announcements (`markx/official.py`). Only an official channel is ever followed by INSIGHT itself ("added
automatically", one-tap undo); an event with none shows "official source not found", and a lawsuit, a regulator's
action or a scoop "no official source".

**Item filter** *(0196, built v10.18)* — a source's rule for which of its items are shown (a release, not a per-commit
build), proposed once by the worker from the source's recent items and applied by code at store time
(`utils/item_filter.py`, `source_filters`, `posts.filtered_by`); a hidden item is stored and kept, never deleted.
