# 0230 — Families and collisions: a family is its maker's and its stem; a relation never crosses two makers' namesakes (Stealth v10.25, slice E)

Status: **built, module tests pass, switched off; not measured on real data** (the scratch Postgres was wiped at
13:15 UTC on 2026-11-19 and the owner stopped real-data testing and production requests; see "Not done"). Backlog
items 0225 #3, #4, #25. No migration. Names below are invented; the real rows (read from the server by GET before the stop order)
are in the main checkout's `plan/research/v1025/e/` (private).

## What was wrong

- **#3 another maker's thing inside a family.** A versioned name's family is the entity its family key aliases
  (`identity.entity_for`), whatever the maker: a quantisation, merge or uncensored fine-tune of "Orbit 4" by the
  account Kestrel became a member of Vantor's family Orbit (the server's largest open family holds ~100 such builds by
  name; another family holds a second maker's "Zentra Orbit 5" and a code project named after it).
- **#4 a member's name as a family's.** When the family key is the name of one of the family's own members (Haiku's
  `family` field "Orbit Argon" for "Orbit Argon 3", where "Orbit Argon" is a variant of Orbit; "Lumen 11" for
  "Lumen 11 24H2", where "Lumen 11" is a version of Lumen), the version's parent was that member: a family named after
  one member, beside the real one. A short stem shared by another maker's model code ("HY368" parses as family "hy")
  put a thermostat under an unrelated "Hy".
- **#25 a relation through a name collision.** The exchange "Orbit" (an org in its post, span "Orbit exchange") is
  linked by its name key to Vantor's model Orbit; the post's stated `released` ("Orbit released Orbit dollar") passed
  `corroborated` (the coin's maker is "Orbit") and became the model's relation. Why the name was never split:
  1. **asked once, before the evidence existed**: the collision question is asked once an entity (`Asked.collide`);
     the server's archive backfill (2026-11-10) brought the 2018 posts after the name was asked;
  2. **the sample never showed them**: it took one mention per (type, maker) first, and a busy name has more such
     pairs than the sample's 8 places, so 0220's one-per-year pass never ran for it;
  3. **never applied**: a split two runs agree on is only queued for the owner (`facts.on` / `facts.split` false),
     and the owner now sees only flagged items (0222). The model's page has no open collision item.
  The second case (a code tool's name held by the 2021 model and today's agent, both by one maker: "based_on" the old
  base model) is the same identity question across years; the maker rule below cannot see it (one maker).

## What changed (identity owns each decision)

1. **A family is its maker's** (`identity.family_makers`, `other_maker`, `maker_fits`): a family's makers are the maker
   its members and names state most, plus any other a fifth of them state (a lab beside its parent company); two
   stated makers are one when they are one cluster, one's words are in the other's ("Vantor" / "Vantor AI"), or one
   names the family ("Orbit Team"). A family with fewer than 3 stated makers is not judged. A new versioned name whose
   stated maker is none of its family's is **a thing of its own maker** (`level` thing, parent its maker's entity, its
   fields kept) with a **`based_on` edge to the family** (`identity.based_on_family`, mx_connections rule
   `family_maker`, shown in the page's Links: `graph.entity_relations` reads it beside `stated`).
2. **A family is its stem** (`identity.family_stem`): a family key that resolves to a version, variant or checkpoint
   of a family is that family (climbed at most 3 times).
3. **The data already made** (`entity_repair.family_home`, a new last repair step, idempotent, a step like the others
   under the stage's budget): a version under a member gets the member's family (mx_entity_fixes `family_stem`, the old
   parent kept); another maker's thing under a family becomes a thing of its own maker, `based_on` the family
   (`family_maker`, the old level and parent kept). An org-like parent stays `reparent`'s.
4. **A relation never crosses two makers' namesakes** (`identity.namesakes`, called by `graph._same_makers` for both the
   stated relations and ent-v5's derived ones): each side's mention must be about its entity's maker: the maker the
   post gives the mention (an org or person mention is its own maker; a thing's, its stated maker) and the entity's (an
   org or person is its own; a thing's, its stated maker), both known, must fit (same key, one's words in the other's,
   or one cluster by their aliases). The exchange's "Orbit released Orbit dollar" no longer lands on the model.
5. **The collision question sees the namesake** (`collide_sample`, `suspect_mention`, `asked_from`): the sample shows,
   first and up to half of its places, one mention per (type, maker) that may be another maker's namesake (an org
   mention of a thing or the reverse, a stated maker that does not fit) and the name's oldest post; and a name whose
   posts now go back before the oldest year its question showed is **asked again** (`collide.older` in the counts;
   one question for each step back: the new sample holds the oldest post). Splits stay the owner's (facts off).

## Measured

Before the wipe (the head as first built, every rule on; S1's names are synthetic and state no maker, so this is the
cost of the code, not of its changes):

| | base (v1025) | head | |
|---|---|---|---|
| entities stage on v1024srv_s1 (budget 45, the server's plan settings, rolled back; warm runs) | 32.1 s wall, 16.0 s CPU, 398 MB | 29.1 / 35.0 s, 16.0 / 16.4 s CPU, 400 / 401 MB | the new repair step 0.40-0.46 s |
| family_home over the whole book (v1024srv_s1, 4,816 versions) | | 0.26 s | 0 changes: the synthetic names state no maker |

## Not done (the owner's stop order, 2026-11-19)

- **How many members move out, how many family names change, how many relations drop**: not measured. `meas.py`
  (private folder) counts all three on a clone in one pass (rolled back); S1's synthetic names have no makers or real
  families, so its 0/0/0 says nothing. Needs a clone of real data (prep_mxreal, or a newer server copy).
- **The frozen sample of >= 150 family memberships labelled blind by Haiku**: not done (no real data). The bar
  (97% / Wilson 90%) is unmet, so the three rules that change what the reader sees ship **off**
  (entity_bands.json `families`: `maker`, `stem`, `namesakes` false; off, linking, the repair step and the relations
  behave as in v10.24, a test says so). The collision question's new sample and its re-ask are on: questions only,
  never applied (a split stays the owner's).
- **The collision re-ask's cost on the server** (how many names' posts go back before their question's oldest year
  after the 11-10 archive backfill): unknown; COLLIDE_CAP (1,000 a run) bounds it.
- The second #25 case (one maker's two things of one name across years) is not fixed: it needs the split applied
  (facts.split, the owner's switch) or a version line that dates its relations.

## Risks

- A maker named only by its parent company's other brand (a lab stated without the company's name, under a fifth of
  the family's stated makers) is read as another maker: its versions would leave the family. FAMILY_MAKER_SHARE and
  FAMILY_MAKER_MIN are guesses until the labelled sample.
- The namesake rule drops a relation whose side's mention states a maker the entity does not hold under any alias
  (a subsidiary unmerged with its parent).
- The new sample order changes which mentions a collision question shows; 0184's measures (v1 50/53, v2 54/54) were on
  the old order.

## Tests

`test_markx_entity_fixes` (+6: another maker's thing based on the family; off by default nothing changes; too few
stated makers keeps members; a member's name is never a family; the repair re-homes the old data, logged and
idempotent; the sample's suspects and oldest post), `test_markx_timeline` (+1: a relation never crosses two makers'
namesakes), and unchanged `test_markx_entities`, `_entity_facts`, `_entity_guards`, `test_markx_graph`,
`test_markx_handles`, `test_voice_owner`: 196 pass. (`test_markx_entity_fixes`' resumable-repairs test now counts the
fifth step.)

## Files outside slice E's

`entity_repair.py` (the new step `family_home` and its config key: slice A's repairs module, an addition at the end of
STEPS), `graph.py` (`_same_makers` around the two relation readers, `entity_relations` reading rule `family_maker`:
slice I's relations code, a filter and one rule added), `entity_bands.json` (a `families` block).
