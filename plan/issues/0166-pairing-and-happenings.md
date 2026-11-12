# 0166 — Pairing and happenings: one module decides what may be compared (spec + built)

From the architecture review of the connection layer (2026-11-12, candidates 1 and 2; 3–5 later). Owner: "don't be a
tactical programmer, focus on strategy". Names below are invented.

## The problem

"Which pairs of posts may ever be compared" was decided in eight places, each with private gates: the candidate
sources (embedding ±72 h at cosine 0.65, nearest 8; story centroids 0.70 / 14 d; entity subjects of five types
±72 h; Mark IX's joins; late bursts), decide's re-gates (0.65 again, the window, 20 words, a roundup as a whole,
0.70 / 14 d again, the connect bar 0.60 / 30 d / 2 voices, the document merges), graph (≥ 30 d; 30–180 d at 0.75),
back (14 d / 7 d / 72 h, 0.70, its type list), later (its own type rule, quiet 14 d) and Mark IX's rules. The post's
date was computed three ways, a page's key five ways, a voice six ways. Two lone posts 72 h–30 d apart had no path,
and the reading's main {action, actors, object, numbers, date} reached no gate: "Acme acquired Widgetco" read the same
in a Russian and an English post 79 h apart was never paired.

## What to build

1. **Pairing** (`markx/pairing.py`): one deep module. Its interface: `find(cur, relation, post_ids, sources=)` (the
   relation's candidates touching these posts, stored once per source), `admits` / `admits_stories` (may a stored
   pair be judged), `story_pairs` (stories by their centroids within the story window), `policy(relation, **bars)`,
   and the basics (`post_date`, `is_voice` / `voices` / `independent`, `page_key` / `page_address`, `document_key`).
   One policy row per relation (window, cosine bars, entity-type list, independence, unit and roundup rule). The
   sources move behind it unchanged; candidates.py and decide.py become callers. Behaviour-identical, proved.
2. **Happening** (`markx/happening.py`): a reading as a key, Pairing's fifth source, behind an mx_settings flag, off.
3. **Words**: `GLOSSARY.md` at the root.

## Built (Stealth v10.14, branch `pairing`)

### 1. Pairing (behaviour-identical)

- Relations: `same_story` (the join, pair and merge questions; sources embedding, centroid, link, entity, burst,
  document, happening) and `connected` (decide's connect questions; centroid). Their rows hold the bars the old code
  wrote down (72 h, 0.65, 8 nearest, five types, 72 h after the first linker, 0.70 / 14 d, 30 d documents, 20 words,
  roundups never whole; connected 0.60 / 30 d / 2 voices). `decide.Config`'s bars default to the rows and override
  them (`Config.same_story()`, `Config.connected()`), so recorded configs read the same.
- Moved: `Posts`, the five stored sources, `document_key`, `centroid_cosines`, `Documents`, decide's candidate gate
  (`admits`), its story gate (`admits_stories`), the story-pair finding in `think` and in `connections`
  (`story_pairs`), plan_pass2's days and bar. back reads Pairing's post date and page address, later its page key,
  tasks and decide its voice rule (all the same values as before). Importers of `SPECIFIC_TYPES` and `document_key`
  read Pairing's.
- Equivalence: `tests/test_markx_pairing.py` runs the old code (verbatim copies at d16336f, `tests/legacy/`) and the
  new on the same data: the candidate job (every source, a subset, one source alone, the job's run in steps) on a
  seeded world, the same rows and counts; plan_pass1 / plan_pass2 on 60 seeded random worlds × 3 configs, the same
  questions; three rounds of the decision run (answered alike), the same tasks, memberships and connections. Changing a
  bar or a gate in Pairing fails them (checked).
- On a scratch copy of the local server copy (two copies, migrated, mx_candidates set aside and regenerated from
  nothing for all 20,742 embedded posts): old 21,931 rows, new 21,931, **0 differ** (scores included). A full decision
  run at one clock on two fresh copies, old code and new: the same questions (check 131, pair 1,232, join 494, merge
  67), the same 708 memberships, the same connections, the same check, headline and back tasks. Alias and collide
  questions differ between any two runs (new entities get random ids; an old-vs-old control differs as much), and one
  perspective task followed them: the old and the new code read the same database into the same 108 perspective
  contexts.

### Basics that still differ (left alone; listed for the anchors step)

| | Pairing (candidates, decide, back, later, tasks) | Elsewhere |
|---|---|---|
| post date | surfaced, else published, else fetched | graph: published first; news: published, else fetched (window), published first (rows); the burst source measures its 72 h in Mark IX's time (published, else fetched) |
| page key | `page_key`: a paper by its id, else `page_address` (host/path, no home, profile or subreddit) | back compares by `page_address` (a paper's versions are different pages there); graph's `_page` (lab form, keeps a video's and a thread's query, no profile rule); burst: Mark IX's stored target address and its home-page rule; documents: `document_key`; Mark IX: `story_rules.page_key` |
| voices | distinct sources, a saved post none | burst: different Mark IX places; link: none (Mark IX's joins); back: a story's members counted by source with saved ones counted; later: one source is enough, the story's own sources' reposts out; graph: the same source allowed at p 0.9 |

### 2. Happening (off: mx_settings `pairing_happening`)

- **Key** = (group, parties, stage, date, money). Group from read-v2's ACTIONS (and verbs the model writes outside
  them): release, deal, funding, legal, people, pricing, research, announcement; `reported` and `other` none.
  Parties: actors and object resolved to the post's ent-v3 mentions (by name key, else the earliest longest mention
  inside the name), the mention's root entity else its name key, unordered; free text, places and venues are no
  party; a thing whose maker is another party is that party. Fewer than 2 parties: no key. A roundup: no key.
- **One happening** = one group, 2+ shared parties, money not more than 30% apart, stated days within the window.
- **Defaults from E1** (`plan/research/exp-2026-11-12/e1`, 2+ shared separate parties 49/52 right, one participant
  8/21): windows deal 30 d, people 14 d, legal 7 d, the rest 72 h; only the measured groups (deal, funding, legal,
  people) are paired; release, research, pricing and announcement keys wait for their measurement.
- **The source**: other source, both voices, within the group's window, not one Mark IX story; mx_candidates source
  `happening` (migration 0109), read by decide as a cosine-less candidate (pair or join questions, never a rule). The
  candidate job runs it for new vectors, new mentions and new readings while the flag is on.
- **Table tests** (`tests/test_markx_happening.py`): a deal; direction flipped ("B joins A"); a founder as a third
  party; one party and free text (none); generic actors and a vague object (none); free text beside two parties (the
  key stands); a maker's own release (none); a partner's release; a leak; a round (raiser and investor) and an unnamed
  raiser (none); a people move; a place and an outlet (no party); reported / other (none); a roundup (none);
  commentary (keeps its key); money within 30% and not, "1,5 млрд $" and "$12,930,300,000"; stated days; Russian and
  English the same key; the source off by default, on: one deal across languages and 79 hours, not the same source,
  not a roundup, not 37 days on, not another amount; legal's 7 days; a release paired only when its group is.
- **On the scratch copy** (5,344 read posts): 444 keys (release 186, research 170, announcement 58, deal 15, legal 6,
  pricing 6, funding 2, people 1); the source makes 4 deal pairs, 2 of them found by no other source (one across
  languages an hour apart, one 9 days apart); with every group paired it would make 23 (release 9, research 8, deal 4,
  announcement 2), 6 new.

## Next (not built)

- **Anchors (review candidate 3)**: back and later take an Anchor (a Mark IX story, a Mark X story, a happening) and ask
  Pairing for follow-ups. Needs: a `follows_up` / `develops` relation row (E6: deal 3–120 d 12/12, legal 3–30 d, never
  funding or one-participant people); one page key for back and later (the paper difference above); one voice rule
  for a story (back counts saved members); Mark X stories readable as anchors (mx_stories / mx_story_posts, not only
  story_posts); a happening stored per post (a table, so an anchor's happening is read, not recomputed); later's
  `specific()` type rule becomes the anchor's happening first, its subject second; graph's post date decided (published
  first today).
- **A closed event-type field in the read guide** (E1: 60 of 106 misses were the group: a filing read as filed,
  published, announced, launched or updated). Never a headline word list (it misfired in E1).
- **Units (candidate 4)**: a roundup's items as units, so a happening inside a digest gets a key.
- **Relations triples stored (candidate 5)**: the entities answer's `relations` as happening evidence.
- **Voice of a repost**: the original author (E1); Pairing's voice is the source today.
- Measure release / research keys before pairing them (their 72-hour neighbours already exist).
