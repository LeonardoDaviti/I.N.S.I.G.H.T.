# 0184 — Entity identity: one module owns what an entity is (Stealth v10.17, slice I) — design, measured, not built

Names below are invented; the real rows are in the private notes (`plan/research/identity-1017/notes.md`).
**Migration 0126+** (number assigned at build). Nothing here is code yet.

## The problem

The owner asked INSIGHT "what is Vexa?" (a terminal app for running coding agents, invented name). The answer was a
page holding three things: the app (2 posts, 2026), a 2003 blog post about an RSS parsing library also called "VEXA",
and a 2010 magazine article about an unrelated project. The entity was typed `other`, had no maker, and its card said
only "Vexa — other". The same class, seen on the server:

- **One name, several things, joined by the name alone.** Linking (`identity.resolve_mention`) gives a mention the
  entity its name key aliases; when that entity holds nothing to compare (no maker, type `other`), every later
  "Vexa" in any post, from any year, joins it.
- **A generic word becomes a thing.** "Terminal" (a terminal in general) an entity typed `software`; "Orbit Devs"
  leaving a stray entity "Devs".
- **Two things of one name not told apart:** an org "Kestrel" and a robot family "Kestrel"; a person "Mara" and
  "Mara Quill".
- **Products never get a maker.** A product's maker is the first run's majority of its mentions' stated makers; when
  the first posts state none, it stays none forever, even when later posts or its own repository say who makes it.
- **Nothing says what a thing is.** Cards show name and type; search ranks posts by word and cannot say
  "Vexa — terminal app (3) · voice mode of a chat app (1) · a game studio's project (1)".

## What the code does today (the map)

### Who decides "this mention = that entity"
| Where | What it decides |
|---|---|
| `markx/identity.py:674` `resolve_mention` | a mention's entity: its pin, else a component (0165 A), else **its name key's alias** (`Book.by_key`, `:254`). The only linking decision; a key has one entity. |
| `markx/identity.py:755` `make_entities`, `:578` `entity_for` | a key with no alias gets an entity made from the run's mentions of it: **type and maker from their majority (`_majority`, `:512`), written once** and never revisited. |
| `markx/identity.py:566` `_maker_entity` | a stated maker string becomes (or finds) an org entity. |
| `markx/identity.py:1391` `odd`, `:1955` `collisions` | the collision judge (kind `collide`, guide `collide-v1`) is asked **only when a key's mentions differ in type or stated maker**; two of three runs splitting puts a `split` proposal in the queue (`:2001`); **never applied**. |
| `markx/identity.py:1214` `decide_pair` and the pool (`:944`-`:1131`) | two *different* names merged (rules, `alias-v1`, `alias2`, guards). Never sees one name standing for two things. |
| `markx/entity_answers.py:69` `split` | the owner's `split` answer: each extra sense an entity named "Vexa (<what>)", **maker NULL**, the question's shown mentions pinned there; every later mention of the key still goes to the first entity by key. |
| `markx/components.py` (via `identity.py:690`) | a span naming a product's component is sent to the component's entity (0165 A, off). |
| `markx/ent42.py` | extraction's merge of the second question (`cite`); no identity decision. |
| `markx/names.py:47` `key` | the name key; a spelling rule, not an identity decision. |

The worker's identity questions (`schemas.KINDS`): `alias` / `alias2` (`alias-v1`: are two names one thing?),
`collide` (`collide-v1`: one name, several things?, the one that already answers "what" per sense), `rename`
(`rename-v1`), and `identity` (`identity-v1`, research's "are two accounts one maker?", 0162; not about mentions).

### Who decides kind and maker (the same decision, made eight times)
| Where | How |
|---|---|
| `identity.py:403` `Book.label`, `:409` `shown_type`; `entity_repair.py:675` `shown` | the shown name and type by evidence (0164). |
| `identity.py:637` `maker_root`, `:643` `same_maker` | a stated maker string read through its alias. |
| `timeline.py:63` `maker_of` | the stated maker's cluster, else an org/person parent's. |
| `entity_views.py:85` `_ent_view` (`:91`), `:263` `maker_candidates` | the card's maker; repository owners proposed. |
| `search.py:343-348` `entity_cards` | `COALESCE(e.maker, parent's name)`. |
| `perspectives.py:163` `Makers`, `:294` `Story._maker` | who makes a story's subject (stated makers, orgs as actor, ancestors). |
| `services/discover_main_source.py:364` `_actor` | the story's maker, else the org named as actor in half the members. |
| `rename.py:80` `maker_index`; `entity_repair.py:363` `_maker_of`; `research.py:1104-1116` | the maker index for renames; a family's maker for the prefix repair; the maker page for research. |

Each reads `mx_entities.maker` (a string, first run's majority) and walks the book its own way. None knows *what*
the thing is, and none can say "the name is right but this post means something else".

## Measured (2026-11-13)

**Data.** `insight_lab` holds no Mark X entities (its schema stops at migration 0068), so the measurement used a
scratch copy of the 2026-11-05 server copy with its entities built (5,031 posts, 18,556 mentions, 8,741 entity
clusters), plus read-only GETs to the server (the open review queue, 40 entity pages and their posts). The scratch
copy was dropped afterwards.

**Population (lab copy, every cluster counted):**

| | count | share |
|---|---|---|
| clusters | 8,741 | |
| name-only: type `other`, no maker, no parent | 1,004 | 11.5% |
| bare names: one word, no digit, no maker, no parent | 2,083 | 23.8% (their mentions: 32.3%) |
| ... of them with 2+ posts | 544 | 6.2% of clusters |
| products (model, product, software) with no maker anywhere | 1,372 of 3,898 | 35.2% |
| ... with 2+ posts | 315 of 957 | 32.9% |
| ... with no maker though one of their mentions states one | 142 of 1,372 | 10.3% |
| bare names with 2+ posts that the collision judge's trigger (`odd`: types or makers differ) ever asks | 93 of 544 | 17.1% |
| later posts of a bare name sharing a source or a co-named entity with an earlier post of it | 3,387 of 4,015 | 84.4% |

**Blind labels, two labellers** (the words around the name, no type or maker shown):

| Sample | Result | Wilson 95% | Agreement |
|---|---|---|---|
| 40 short one-word names with 2+ posts (frame 501), random | several things: **0/40**; a company and its same-name product: 3/40 | 0-8.8%; 2.6-19.9% | 40/40 |
| 40 one-word names that are a lowercase word in 5+ posts (frame 340), random | generic word: **1/40** (+1 mixed by one labeller) | 0.4-12.9% | 39/40 |

So on 29 days of fetched posts the collision is rare: the lab copy holds almost no archive (5 clusters have posts
more than a year apart). **On the server, with archives back to 2003, it is not:**
the server's review queue holds **1,774 open collision items** (`collide-v1` splits that two of three runs agreed
on, queued and never applied), beside 10,322 alias items. A random 40 of them, with each entity's posts read by GET
(up to 6 a entity, 166 posts), labelled blind by two labellers before they saw the judge's proposal:

| | Result | Wilson 95% |
|---|---|---|
| the entity holds several unrelated things (blind) | **33/40** (A) / 34/40 (B); agreement 39/40 | 68.0-91.3% |
| the judge's split confirmed by the posts shown | 33/40; 6 more name a sense the 6 posts shown don't hold (unverifiable, plausible); 1 disputed (an app and its file format: part, not different) | 33/34 = 97.1% (85.1-99.5) of the verifiable |
| a proposed sense's "what" line right, where the posts show that sense | **77/77** (9 of the 86 senses not in the posts shown; one loose, one a duplicate sense) | 95.3-100% |
| the posts show a thing the judge's senses miss (it sees 8 mentions) | 9/40 | 12.3-37.5% |

So the question that would own the facts already answers them well: it finds real collisions, and its one-line
"what" is right whenever it can be checked. What fails is around it: it is asked only for the 17% of bare names whose
mentions differ in type or maker, its split is never applied, a split's later mentions still go by the name, and one
look at 8 mentions misses a quarter of the senses (an archive name like "Nara" can have five).

**What the worker does now (server, overview GET):** `alias` 277,985 answered, `collide` 12,337, `entities` 212,475
(posts); the last run: 219 keys odd, 12 asked, 176 one thing, 1 queued.

## The decision (owner's rules applied)

One deep module, **`markx/entity_facts.py`**, owns an entity's **identity facts**: its kind, its maker, a one-line
"what it is", the few words that tell it from another thing of the same name, and whether the name is a generic word.
Linking a bare name asks it; the timeline, cards, search and Discover read it. The facts come from the existing
"one name, several things?" question (`collide`), which gains fields (guide `collide-v2`), not from a new worker kind.
Every fix deepens this module; no caller re-derives a maker or a kind.

### Design it twice

**A. Senses on the name (chosen).** A name key keeps one entity per *sense*; the facts say what each sense is. A new
mention of a bare name is placed by rule when its own fields and its post agree with one sense's facts, and otherwise
waits for one `collide-v2` question that sees the known senses and the new mentions and assigns each (a known sense,
a new sense, or a generic word). A placement is a pin (`mx_entity_pins`, a row, `by` = `facts`), so the key, the
redirects and every reader stay as they are.

**B. A sense per context, joined by pairs.** A bare-name mention in a post with no agreeing context makes its own
provisional entity; the alias pool pairs it with the name's other entities, and `alias-v2` (each side's kind, maker
and what, as extra fields) decides `same` / `different`. Facts are a by-product of pair questions.

| | A. senses on the name | B. a sense per context |
|---|---|---|
| Which question | `collide` (one entity, its mentions) | `alias` (two entities) |
| Calls for a name with *k* senses and *n* new posts | 1 a batch of new mentions | up to *k* a new post |
| Pages until answered | the post shows under the name, marked unchecked | the post sits on a one-post entity of its own |
| Fit with the guards | none touched | **fights the chain guard** (a cluster of 2+ names never joins another; at most 6 names): a popular bare name cannot be rebuilt by pairwise merges |
| Rows | facts a sense, pins only for moved mentions | an entity a context, merges back |
| Server memory | facts read per chunk (500 mentions) | the book grows by an entity a context (the worker loads the book whole) |
| What it fixes | collisions, generic words, missing makers, what-it-is | collisions only; generic words and makers need more |

**A is chosen:** it asks fewer questions, leaves the merge guards untouched, keeps a page whole while a question
waits, and the question it extends already produces a sense's "what" (the server's queued splits all carry one,
77/77 right where checkable). Placing each new mention against the known senses also repairs the judge's one
weakness measured above, a single look at 8 mentions missing senses: a mention no sense fits is asked again and
becomes a new sense.

## The design (A)

### Interface (two entry points)

```python
# markx/entity_facts.py — Identity facts
def place(cur, book, mentions, *, ask, run_id) -> Placement:
    """The entities stage, for every mention about to be linked (identity.resolve_mention calls it for a bare key):
    the entity it goes to (a known sense, by rule), or `wait` (linked by key as today, marked unchecked, its entity
    asked). Reads the answers since and applies them: facts rows, pins, new sense entities. Paged by the stage's
    chunks; never loads every fact."""

def read(cur, roots, *, senses=False) -> Dict[str, Facts]:
    """Every reader: {root: Facts(kind, maker {id, name} | None, what, context, generic, by, senses?)} in one query by
    id (an index on entity_id, current rows). `senses`: the other entities sharing the root's name key, each with its
    what and post count (search's grouping)."""
```

Everything else (the rules, the question's input and answer, the backfill cursor, the maker consolidation) is
inside.

### Facts schema (migration 0126+)

`mx_entity_facts`: `id`, `entity_id` (→ mx_entities), `kind` (an entity type, or `generic`), `maker_id`
(→ mx_entities, NULL), `maker_name`, `what` (one line, at most 80 characters), `context` (text[], up to 4
distinguishing words: field, platform, place, era), `by` (`rule:mentions` | `rule:address` | `haiku` | `owner`),
`guide`, `call_id`, `confidence`, `evidence` jsonb, `created_at`, `superseded_at`, `superseded_by`. One current row
an entity (`UNIQUE (entity_id) WHERE superseded_at IS NULL`). Keep everything: a new fact supersedes, never updates;
an owner's fact is never superseded by a rule or Haiku.

`mx_entity_pins` gains `by` (`owner` default | `facts`), `call_id`, `from_entity` (the link it replaced). An owner's
undo of a facts pin is final (that mention is never re-pinned by facts). `mx_entity_queue.kind` may be `facts`
(a split below the bar, for the owner).

`mx_mentions` gains `placed` (NULL: not a bare key, linked as today | `rule:maker` | `rule:context` | `facts` |
`wait`): how the module placed the mention, a flag on the row the stage already writes (`entity_id`), no new row a
mention and nothing the book loads. A `wait` mention shows on its name's page marked "not checked yet" and is left
out of the timeline's birth and outside lines, the card's counts and search's sense counts until it is placed.

`mx_entities.status` keeps `not_entity`; a generic sense is a sense entity with kind `generic` and status
`not_entity`, so every reader that already skips `not_entity` hides it.

### How a mention is placed

A key is **bare** when it is one word (or one word after `the`), holds no digit, and its entity has no maker fact;
or when its name has 2+ sense entities. Every other key links as today (versions, makers and families already tell
things apart).

For a bare key, in order (rules first, no call):
1. the mention's stated maker names one sense's maker (`same_maker`): that sense; it names a maker that no sense has
   while every sense has one: unchecked (step 3), the question may make it a new sense;
2. its post shares a source or a co-named entity with a post already placed in exactly one sense: that sense
   (84% of later posts on the lab copy; its precision is part of the bar below);
3. otherwise: linked by key as today, **unchecked** (`placed` = `wait`), and the entity is asked.

The question (`collide-v2`) for an entity with unchecked mentions: its known senses (each one's what, maker, kind,
years, two placed mentions) and up to 8 unchecked mentions (the words around the name, the post's title and date).
The guide asks, for each mention, which sense (`S1`, `S2`, ..., `new`, `generic`, `unclear`), and for each sense,
new or known: `what`, `kind`, `maker` as the posts state it (none when no post says), `context`. A first question
for a bare name with 2+ posts and no facts has no known senses (the backfill, below).

Applying an answer (when the switch is on): a mention in a known sense other than its key's entity is pinned there
(`by` facts); a `new` sense agreed by two runs (the existing majority rule, `split_of`) becomes an entity
("Vexa (terminal app)", the sense's kind and maker, status provisional) and its mentions are pinned; `generic`
agreed by two runs: a `generic` sense entity, `not_entity`; `unclear` stays where it is. A known sense's facts are
rewritten only when the answer's differ (a new row). Below the bar, or with the switch off, an answer is a
`facts` queue item, as `collide` splits are today.

The trigger widens from "types or makers differ" (`odd`) to "a bare key with unchecked mentions"; `odd` stays a
reason to ask. A key asked waits for its answer before another question (as `collide` does).

### Makers for products (no call)

Inside `place`'s pass, each touched sense's maker fact is consolidated from, in order: the owner's; the majority of
its mentions' stated makers over all its posts (not the first run's: 142 of 1,372 makerless products on the lab copy
have one stated); its own addresses' owner when the repository rule names an org or person entity
(`maker_candidates`'s rule, today only proposed); the question's `maker`. `mx_entities.maker` is left as made
(it still decides identity in the pool); readers read the fact.

### Re-linking what is there (keep everything)

A **backfill** in the entities stage, paged by entity id (1,000 a page, its cursor in the run's counts, resumable as
`shown.after` is): each bare key with 2+ posts and no facts is asked once (no known senses). Answers apply as above:
pins with `from_entity`, never an update of a stored link without its row. Undo is the pin's `undone_at`. Until its
entity is asked, a stored mention keeps `placed` NULL and shows as today. A full relink pass reads pins as it does
now, so it moves nothing back, and `place` skips a mention already placed (the nightly pass adds no rule work).

### Readers (which callers change)

| Caller | Change |
|---|---|
| `timeline.py:63` `maker_of` | `entity_facts.read(...).maker`; the birth and "outside" lines only from the sense's own posts (pins already do this) |
| `entity_views._ent_view` / card / list | maker from facts, plus the `what` line; `_list_book` reads pins of its rows only (today it reads every current pin in the API) |
| `search.entity_cards` | one card a name key: its senses with what and post counts ("Vexa — terminal app (3) · voice mode (1) · game project (1)"); posts grouped by sense in "entity first" |
| `discover_main_source._actor`, `perspectives.Makers` | a subject's maker from facts (one query for the story's subjects) |
| `rename.maker_index`, `entity_repair._maker_of`, `research.py` maker page | facts' maker (worker side: read per chunk) |
| `identity.resolve_mention` | calls `entity_facts.place` for a bare key; nothing else in the linking changes |

### Cost

- **Worker calls.** Backfill: bare keys with 2+ posts, 6.2% of clusters on the lab copy; scaled to the server's
  ~290k entities (`embed_name` answered) about **18k `collide-v2` calls once**, paged (e.g. 2,000 a day).
  Incremental: the later posts of bare names the rules leave unplaced, 628 in 29 days for 5,031 posts on the lab
  copy, **at most 0.125 calls a post** (one call covers up to 8 mentions of an entity, so fewer), against ~1.3 `alias`
  calls a post today. A `new` sense costs one more run (the two-run agreement).
- **Server memory.** API: ~0 added; `read` is one indexed query by the ids a page already holds; no book. The list's
  pin read becomes per row (less than today). Worker: facts read per mention chunk (500) and per backfill page
  (1,000 entities); the book gains only the facts pins it already loads with every pin (`load_book` reads all
  current pins): if as many as a tenth of the server's bare-name mentions moved (~20k of ~700k mentions), that is
  ~20k small rows, a few MB. Rows: one facts row a sense; pins only for moved mentions.
- **Tokens.** `collide-v2`'s answer adds kind, maker and context per sense (~30 output tokens a sense).

## Test plan (invented names, no database for the rules; the stage on a test database)

Name collisions, each a test:
1. "VEXA" an RSS library (one 2003 post, the key's entity) and "Vexa" the terminal app (two 2026 posts, no source
   or co-named entity in common): the 2026 mentions wait (`wait`, not counted on the library's card or timeline), one
   question makes two senses, each with its what; the app's timeline starts in 2026, its card says "terminal app",
   no maker invented.
2. "Kestrel" an org and "Kestrel" a robot family by another maker: the mention stating the other maker goes to the
   family's sense by rule 1, without a call.
3. "Terminal" used as a common word in three posts: one `generic` sense, `not_entity`, absent from lists, cards and
   timelines; a fourth post naming a product "Terminal" by a stated maker becomes a product sense.
4. "Orbit Devs" (an account's display name) and a stray "Devs": "Devs" placed `generic` (or the account's sense),
   never a thing of its own on the list.
5. "Mara" (a person, one post) and "Mara Quill": unchanged by this module (two words is not bare; the alias question
   decides) — guards that the module does not touch non-bare keys.
6. A product "Tessel" with no maker in its first post, a later post stating "Tessel by Zentra": the maker fact becomes
   Zentra (`rule:mentions`); `mx_entities.maker` unchanged.
7. Rule 2: a later post from the same source as a placed one goes to that sense without a question.
8. Keep everything: a relink is a pin with `from_entity`; an owner's undo of it is final; an owner's fact is never
   superseded; a full relink pass moves nothing back.
9. Switch off: answers become `facts` queue items, nothing pinned (the deploy changes no page).
10. Search: a query "vexa" gives one card with three senses and their post counts; "entity first" groups by sense.
11. The API: `read` issues one query for a page's ids (a test counts queries); no `load_book` added.

## The measurement before switching on (the bar)

Measured in the lab against the current guide (`collide-v1`) on a frozen, held-out set (the guide and code md5'd
before the first run): the server's open collision items (read by GET) plus bare names with 2+ posts drawn from older
server posts; two blind labellers and a referee; 3 Haiku runs, majority; the first run's numbers are the result.

| What | Bar to switch on |
|---|---|
| a `new` sense applied (a split) | precise **95%**, Wilson lower bound **90%**, on 80+ labelled splits |
| collisions found (of entities labelled several things) | 80% |
| a mention assigned to a known sense | 95% |
| `generic` applied | 95% precise (a named thing is never hidden) |
| `what` right / maker right when given / maker invented | 90% / 95% / at most 2% |
| rule 2 (shared source or co-named entity) | 97% precise on labelled later posts |
| against `collide-v1` on its own items | splits at least as precise |

Today's `collide-v1` stands at 33/34 verifiable splits (97.1%, lower bound 85.1%) on 40 server items, below the
bound's bar only for want of rows: the held-out set needs 80+ verifiable splits.

Then the realdata-check on main and the reader review, before the owner switches it on.

## Not measured (say so before relying on it)
- How many of the 83% of bare names the current trigger never asks hold several things (every server item sampled
  was asked because its mentions' types or makers differed); the backfill's first answers will count it.
- Rule 2's precision; the server's daily post volume (the incremental cost above is per post).

## Built (Stealth v10.18, behind the switch) and measured

**Migration 0137** (0126+ in the plan; 0136 is taken by stored pages on another branch): `mx_entity_facts` as planned
plus `sense_key` (the bare key a sense belongs to: a split's entity, "Vexa (terminal app)", has a key of its own);
`mx_entity_pins.by/call_id/from_entity`; `mx_mentions.placed` (`rule:maker`, `rule:context`, `rule:handle`, `facts`,
`wait`); queue kind `facts`.

**`markx/entity_facts.py`**: `read` (one query by ids, `senses` one more; nothing when the switch is off), `write`
(supersede, never update; an owner's row never superseded), `place` (rule 1 the stated maker; rule 2 a shared source
or co-named entity, its own switch; else `wait`), `place_by_handle` (0168: a bare first name in a post by an account
the owner confirmed as a person's is that person; its own switch), `to_ask` (the entities with `wait` mentions; the
backfill), `known_block` (the question's known senses), `apply` (a settled answer's facts; a two-run split made into
sense entities through `entity_answers.split(by="facts")`, else queued as before), `makers` (a product's maker from
its mentions' stated makers over all its posts, `rule:mentions`). Deepened, not duplicated: `identity.collisions`
asks the widened set and hands settled answers to `apply`; `identity.stage` places each linked chunk;
`entity_answers.split` makes the senses for the owner and the facts alike. Readers: the entity list and page (`what`,
the maker when made with none, the name's other senses), search's cards (one card a name, its senses with `what` and
post counts), the timeline's maker. Not wired yet: `perspectives.Makers` / Discover's `_actor` (they read the book
without a cursor), `rename.maker_index`, `entity_repair._maker_of`, research's maker page; the pages' frontend for
`what` / senses.

**The question.** Kind `collide` keeps `collide-v1` until the owner switches on; `collide-v2` (the guide, its schema
`COLLIDE2_SCHEMA`) is a superset of v1's answer (kind, maker as stated, what, context, generic, known sense).

**Measured (2026-11-14), held out:** 60 open collision items from the server's queue (seed 1018; each entity's
posts by GET, up to 8 spread over time, no type or maker guess in the input), both guides asked once (the first run's
numbers), one blind labeller grouping the mentions (no answer shown), a second judge checking v2's `what`, maker and
kind against the posts.

| What (the 0184 bar) | collide-v1 | collide-v2 | bar met? |
|---|---|---|---|
| splits right (95%, low 90%) | 50/53, 94.3% (low 84.6%) | **54/54, 100% (low 93.4%)** | yes on 54 (the plan asked 80+) |
| collisions found (80%) | 50/55 | **54/55 (98%)** | yes |
| mention pairs called different, right | 243/243 | 262/264 (99.2%, low 97.3%) | yes |
| `generic` right (95%) | — | 6/6 | too few to say |
| `what` right (90%) | — | 128/133 right, 4 loose, 1 wrong (96.2%) | yes |
| maker right when given (95%) / invented (<= 2%) | — | 38/38 / 1 of 133 known but not stated (0.8%) | yes |
| rule 2: a shared source means one sense (97%) | | 140/171 (81.9%, low 75.4%) on the labelled pairs | **no: off** (`rule_context`) |

Not measured: rule 1 (the stated maker), `rule:handle`, the backfill's bare names that the old trigger never asked
(the lab measured 0/40 several things among them), a mention assigned to a known sense (needs senses with facts
first). Cost: collide-v1 + v2 on 60 items 0.07 $.

**To switch on** (entity_bands.json `facts`): `on` (the readers and the makers), `split` (the splits: bar met on 54),
`place` (rule 1 and `wait`), `backfill` (cap a run); `collide` to `collide-v2` in `schemas.KINDS`; then the
realdata-check on main and the reader review.

### Round 2 (2026-11-14): the placement rules, measured

| Rule | Held-out rows | Result | Switch |
|---|---|---|---|
| rule 1: a mention whose post states one sense's maker goes to that sense | F1's 235 mentions of names with 2+ senses (labelled senses and makers; a maker "stated" when its name is in the mention's title or words) | places 54; 53/54 right (98.1%, Wilson low 90.2%). The one wrong: an NVIDIA framework mention placed in the NVIDIA sense | **`place`: on** (it acts only once `on` is) |
| rule 2: a shared source | the same pairs | 140/171 (81.9%) | `rule_context`: off |
| the handle rule: a first name in a post by the person's confirmed account | the mxreal copy (49k posts): handles learned from 2+ "Name (@handle)" pairs, a post's own X account or a `by` reference | 18 rows, all orgs (the first word of "Unsloth AI", "NVIDIA AI", "Google DeepMind"), no person: the rule (persons only) has no rows to measure | `rule_handle`: off, unmeasured |

**Placing a mention in a known sense (step 4): built, off.** `entity_facts.place_known` reads the answer's
`"known": "S2"` and pins each such mention to that sense entity (a facts pin, placed `facts`). The answer's facts are
written for the entity only from a group the answer doesn't put in another known sense. The switch is `known`,
unmeasured: it needs senses with facts on the server first, which comes once `on` and `split` are switched on.
