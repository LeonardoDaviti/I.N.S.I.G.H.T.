# 0090 — Mark X entities: one name per thing, its versions and role, and what connects through it

Status: **spec, draft (measured)** (2026-11-04).
- **Part A,** extraction, ships in Shadow: 0086's `entities` task and its `mx_mentions` table.
- **Parts B–F** follow, each merged on its own.

**Constraints:**
- No real channel names in this file or in fixtures.
- Measure on copies.
- Keep everything: a merge leaves a redirect and can be undone, and nothing is deleted.

## Why (the owner, 2026-11-04)
- "The most important part here is entity gathering and connecting posts through entity and understanding their connections."
- "I want to actually make entity extraction best on here, because it serves good for us."
- And on 2026-10-28: entities even from skipped posts. A skipped post about a product shows up later under that product.

## Measured
**v0, names taken from the reading's slots** (background run, 2026-11-04: 150 records, 100 dictionary matches, 69 surges; two blind labellers):
- **Records:** 74% are real things, 48% have the right name, and 36% of version splits are right.
- **A dictionary of known names finds only 16% of the names in posts Haiku hasn't read,** so every post has to be read.
- **Roles decide connections:** only 21% of right matches are a post's main subject.
- **Surges:** 57% are real. The false ones are passing mentions, predecessors and comparisons.

**v1 against v2, its own extraction** (2026-11-04, one blind labeller):
- **The samples:** 93 posts compared (X/Y shuffled, the labeller blind to which was which), and v2's extra fields checked on 120 posts. Both come from the server's 16 days and the lab window, stratified by kind.
- **The two versions:**
  - v1: name, type and main subject;
  - v2: `ent-v2`, with spans, canonical names, roles, maker, version fields and relations.

| | v1 | v2 |
|---|---|---|
| Entries per post | 4.0 | 3.3 |
| Real named things | 93% | **99%** |
| Name right (canonical, complete), of the real ones | 84% | **98%** |
| "Main subject" right when said (precision) | 77% | **94%** |
| Posts whose main thing is missing | **4%** | 10% |
| Share of named things found (estimate) | **99%** | 93% |
| Clean entries (real, name, type and main all right) | 74% | **91%** |

**v2's extra fields (120 posts):**

| Field | Right |
|---|---|
| Roles | 92% (subject 96%, actor 87%, compared 17/17, venue 91%, mention 90%) |
| Makers | 94% |
| Version fields | 53/58 = 91% |
| Relations stated by the post | 47/47 |

**The code checks:** 415/415 spans occur in their post, and 50/51 versions occur in the post.

**What it means:**
- **Most of the gain is having entities as their own task.** v0 → v1 takes names right from 48% to 84%.
- **v2 makes entries clean enough to connect on:** 91% clean, against 74% for v1.
- **v2's weakness is recall.** It skips some small or unusual names: a lab's own product, a visa programme, a country the post is about. 9 of 93 posts lack their main thing, against 4 for v1.
  - **Fix (`ent-v3`):** "always list what the post is mainly about, even if it is small, unknown or not a company or product"; then re-measure.
  - **Wrong entries are rare:** a concept or technique ("ReAct", a named bug), and a city only named as a venue's location.
- **Versions: the model, guarded by code, not a parser alone.**
  - Haiku's fields are right 91% of the time; `entparse.py`, written before seeing the gold, 67%.
  - The parser loses mostly by keeping the maker in the family: "NVIDIA GeForce RTX", where the gold has "RTX".
  - It's right 4 of the 5 times Haiku is wrong. So:
    - the stored fields are Haiku's;
    - code checks that each version occurs in the text;
    - a disagreement between Haiku and the parser goes to your merge queue.
  - The parser's fixes (the maker prefix, ".x" versions, Roman numerals) are measured on fresh posts, not this sample.

**v3 and identity (2026-11-05, held-out days 1–4 Nov, one blind labeller):**
- **`ent-v3`** is v2 plus "always list what the post is mainly about"; concepts and venue cities are not entities. Labelled blind against v2 on the 67 test posts where they differ:

  | | v2 | v3 |
  |---|---|---|
  | Posts missing their main thing | 13% | **3%** |
  | Main subject right when said | 88% | **92%** |
  | Clean entries | 90% | **92%** |
  | Names right | 98% | 96% |

  **Shadow ships v3.**
- **Identity on 479 posts** (1,655 mentions, 1,064 name keys; Haiku's canonical names already join most spellings):

  | Rule | Result |
  |---|---|
  | Maker-prefix alias ("NVIDIA H200" = "H200") | right 9/10. **Adopted** |
  | Short-form alias by suffix | right 2/14. **Rejected:** a fork, a part, an essay about the thing, or a different repository with the same name. Short forms come from extraction's canonical names and from anchors |
  | Version guard (another version stays apart) | 113 of 126 near-misses are other versions and stayed apart; 1 real alias missed ("Gemma E4B" = "Gemma 4 E4B"), a case for the merge queue |
- **Entities as story candidates:**
  - 7 of 11 accepted pairs are right, and they're stories the embeddings missed.
  - Limited to specific subjects (a model or product version, a paper, a repository or a tool, not a company or person alone): 7 of 8.

Data and reports: `plan/research/lab/markx/proto/out/bg/results_ent2.json`, `report_ent2.md`, and `plan/research/mark-x-overnight-2026-11-05-report.md` (private).

## The design
**For each post** (Shadow, every post):
1. **Extract** (Haiku, guide `ent-v3`). The extraction gives:
   - every named thing, typed (org, person, model, product, software, paper, dataset, event, place, law, other);
   - its exact span, copied from the post;
   - a canonical English name, completed only when the post makes it clear ("Opus 5.5" in a post about Anthropic is "Claude Opus 5.5");
   - its role: subject, actor, compared, predecessor, venue or mention;
   - its maker;
   - its version fields (family, version, variant, size, build);
   - the relations the post states (released, acquired, based_on, beats, …).

   Descriptions, generic words, prices and plans are not entities.
2. **Check in code:**
   - every span occurs in the post;
   - every version occurs in the post;
   - types and roles are from their sets.

   Otherwise the answer is invalid and asked again (0086 C). The model never "corrects" a version it doesn't know.
3. **Key:** a name key separate from the shown name. It applies NFKC, every dash as "-", no soft hyphen, casefold and ё→е, splits letter–digit glue ("Qwen3.8" → "qwen 3.8") and treats separators as one. Mixed-script words are flagged.
4. **Version fields:** family, version, variant, size and build, as Haiku gives them (91% right). Code checks each version against the text and compares Haiku's split with the parser's; a disagreement goes to the merge queue. A version compares as a tuple, so "4.10" ≠ "4.1"; a size or a quantisation is never a version.

**Across posts** (part C, identity):
5. **Link:**
   - an exact key in the aliases is a link;
   - a known family with a version or variant never seen creates a child entity (provisional, with its first-seen date and posts);
   - an unknown family creates a provisional family.
   - Haiku decides only real collisions, one name for several things (a model vs a 1965 space flight; a person vs a product). It picks from the candidate ids plus NEW and NOT_ENTITY, writing its evidence first.
6. **Merge conservatively:**
   - **What can merge:**
     - two entities that share an anchor (the same model or repository address, the same official page);
     - "X (Y)" written inside one post;
     - your tap.
   - **Every merge leaves a redirect** and can be undone.
   - **Never by itself:** no merge across different parsed versions or variants without you, and no chain of automatic merges (one bridging alias must not join two families).
7. **The hierarchy:** company → family → version → variant → checkpoint (size, build).
   - A post links to the most specific level it states.
   - Stories use the version level, and pages roll up.

**What uses it** (parts D–F):
- **Connections:**
  - post → entity, with its role;
  - story → entity, its subjects;
  - entity → entity: released, acquired, invested_in, partnered_with, hired, joined, left, leads, based_on, beats, part_of, next_version; each with its post and time.
- **Candidates for the judge:**
  - the same subject entity and version within 72 hours: same event? (0086 B's `entity` source);
  - across months: a follow-up, or the next version? (0091).
- **Surges:** count only posts whose subject is the entity, per exact version, against the entity's own baseline after a 7-day warm-up.
- **Pages and timelines** (0001): releases, papers, incidents, numbers (0095) and people, in order, each with its posts; "since you last looked" (0094).

## Parts
- **A. Extraction in Shadow** (0086 C, `entities`, `mx_mentions`). Done when every post of the last 30 days on a server copy has its entities and every answer passes the code checks.
- **B. The name key and the version parser,** in code.
  - Tests: the gold sets above, kept as regression tests for every new guide version.
  - Done when the parser matches the gold set as well as the measurement says.
- **C. Identity.** The tables:
  - `entities`: id, kind, name, parent, maker, family key, version tuple, variant, status (provisional or confirmed), first seen, and an optional Wikidata id, for companies, people and families only, never for a version;
  - `entity_aliases`: key, entity, language, and where it came from (rule, Haiku, anchor or you);
  - `entity_redirects`;
  - `entity_relations`: a, relation, b, post, call, valid from and to.

  Plus a merge queue on the Mark X page (one tap: same, other version, different).
  - Done when two release weeks' merges and splits are read by hand and the wrong ones fixed (as 0070 did for separators).
- **D. Connections and candidates.** Done when the `entity` candidates' precision for "same event" is measured on your labels.
- **E. Surges per exact version.** Done when the false surges measured on 2026-11-04 (passing mentions, predecessors, comparisons) are gone from a replay of the same days.
- **F. Entity pages and timelines** (with 0001).

## Measure before each part
- **B:** the gold sets above, per field.
- **C:**
  - on 90 days, the share of new names that are a new version of a known family against an unknown family (this decides how much the hard case matters);
  - 150 name pairs labelled same / other version / different;
  - wrong version merges and wrong spelling splits reported apart, never as one number.
- **D:**
  - the judge's precision on `entity` candidates against `embedding` ones;
  - how many stories Mark IX split that entities join.
- **Your 2 hours** (with E1): entities on 60 posts, time-split.

## Known failure modes and guards
From `plan/research/mark-x-entity-identity.md` (2026-11-02) and the background run:

| Failure | Typical cause | Guard |
|---|---|---|
| A description taken for an entity | the reading's slots ("a video of a man running 8 agents") | its own extraction with "not entities" rules; the span check |
| One product split in two | letter–digit glue, dash forms, inflection, Cyrillic forms, a dropped family ("Opus 5.5"), date suffixes, repository name vs marketing name | the name key; canonical names in extraction; aliases from anchors and "X (Y)"; your merge queue |
| Two versions merged | fuzzy matching on whole names (4.6 vs 4.7), "4.10" = "4.1", a dropped variant | exact version and variant fields; fuzzy matching on the family only |
| A size or quantisation read as a version | "Qwen3.8-27B", "EXL3", "Q4_K_M" | size and build fields; the parser's size and build patterns |
| A parent swallowing its children | linking every version to the family's one id | the hierarchy; ids from outside only on families |
| A name collision | one name for a model and an old space flight; a person and a product | types; recent context; Haiku picks among candidates |
| The model "correcting" a new name | it has never seen "Grok 4.7" and writes "Grok 4" | spans copied and checked; versions checked against the text |
| A merge cascade | one alias bridging two families | no automatic chain merges; large clusters reviewed |
| A leak taken for a release | leak posts weeks before the release | first-seen against released on the timeline; a leak is a development, not a new entity |
| Surges from passing mentions | a predecessor or a comparison named in another launch | roles; surges count subjects only, per exact version |
