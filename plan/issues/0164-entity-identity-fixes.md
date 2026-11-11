# 0164 — Entity identity fixes (Stealth v10.13.13)

Four classes of wrong entity identity seen on the server's entity list (2026-11-11, the 30-day top 200, read through
the read-only API; names here are invented). Each is fixed as a class, in the linking and merge rules (what comes)
and as a repair of the data already made (what is there). **Migration 0104** (0103 is main's later rule; renumber at
merge if another lands first).

## The classes, as seen

1. **The name shown is the first name seen.** The cluster holding every mention of a big lab is shown as its
   developer account's display name ("Zentra Devs"); a CEO's cluster by his handle's nickname, typed `org`; a chip
   maker by its handle ("ZentraAI" beside "Zentra", "Zentra Corporation"); a person by the first name alone; an org
   by a rare spelling ("Z.entra" though "Zentra" is the common form).
2. **A product family merged into its maker org.** The org "Zentra AI" holds the names [Vela, Zentra, Zentra AI,
   Zentra Vela]: the family Vela (its versions' parent) was merged into the org through "Zentra Vela", a name Haiku
   typed `org`; the pair-level type guard saw org = org. So "Vela 4"'s family showed as the org. Separately, a
   version named by its maker's name ("Zentra 5" by Zentra) took the org itself as its family (the family key
   "zentra" is the org's alias).
3. **Families split by a brand or maker prefix.** "Nova Lyra 5.1" (family "Nova Lyra") beside "Lyra 5.1" (family
   "Zentra Lyra"); "Cora 5" whose names include "Nova Cora 5" but whose family is a "Cora" beside "Nova
   Cora". (The families were often first written bare, so they are `thing` entities that versions name as parent.)
4. **Maker vs org.** Makers are stated as "Zentra AI" while the org is shown as "Zentra": on the server most such
   pairs were already one cluster (the maker's name an alias of it), but the maker was shown as the stated string, not
   the org. A maker entity made for the hierarchy alone (no mention names it) is never in the alias pool, so if it
   was not merged it never would be.

## Rules (the owner's, kept)
- Keep everything: a wrong merge is undone (its redirect closes, `undone_by` 'repair', the why in its evidence), a
  merge is a redirect (undoable), a changed derived field is logged with its old value (`mx_entity_fixes`).
- The owner's answers win: a merge the owner made or answered `same` is never undone (a cluster only the owner's merge
  holds together is left, counted `held`); a pair the owner kept apart or whose merge the owner undid is never merged;
  an owner's rename (`shown_by` 'owner') is never replaced.
- The class, never a name list; the version guard stays (different versions never merge).

## Built

### Forward (markx/identity.py)
- **Cluster type guard** (`org_family`): `Book.sides(cluster)` splits a cluster into its family side (a `family`
  entity or a name a version names as parent, whose mentions are mostly not org/person; plus a name that is a family
  name with words in front, whatever its type) and its org side (org or person, neither). An automatic merge (a rule,
  Haiku, the second opinion) between a cluster with a family and one with an org goes to the queue (`type`, reasons
  `org_family`). The owner's answers are not guarded.
- **A version's family is never an org** (`family_under`): when a new version's family key aliases an org-like
  cluster, its family is a `family` entity of that name under the org (found again by key, the same maker or none;
  else made; its key's alias stays the org's, so the org's own mentions are untouched).
- **`family_version` rule**: two versions whose families are one cluster, stating the same version, variant, size and
  build in Haiku's fields and the parser's, the same maker or one none: automatic (the version and chain guards hold).
- `Book.types` (each entity's mentions' types, counted; one query as the old DISTINCT was), `Book.etype` (their
  majority), `Book.cluster` (members of a root, the reverse redirects kept while `Redirects` doesn't change),
  `Book.label` / `shown_type` (what views show), `maker_root`, `same_maker`.

### Repairs (markx/entity_repair.py, run first in the entities stage, 25% of its budget, in a savepoint)
1. `org_family`: each cluster with both sides is cut by undoing the fewest automatic redirects separating them
   (greedy on the merge tree: a merge's edge is the two roots it joined, the owner's the two names the owner
   answered). An owner's redirect that crossed the cut only because it went root to root is re-pointed: undone and
   made again between the owner's two names (by 'owner', automatic false, its queue item, `repointed_from`).
   Bounded: 200 undos a run.
2. `reparent`: a version whose parent cluster is org-like gets the family entity (`family_under`); `mx_entity_fixes`
   keeps (kind `org_family`, field `parent`, old, new). Idempotent; 2,000 a run.
3. `families`: the family clusters' names (every member but versions), stripped of a known prefix: a maker cluster's
   names, or a brand (a word in front of 3+ of one maker's family names, owned by one maker). Same remainder, one
   maker (two makers: never), and evidence: a version both state, or for a family stating no maker a version already
   merged with one of the other's. Merge `rule:family_prefix` (never over the owner's apart answers, the type guard,
   at most `MAX_CLUSTER` names). Then `merge_versions`: in every family cluster of 2+ family names, the versions
   stating one version signature merge through `decide_pair` + `chain_guard` (`rule:family_version`).
4. `suffix` (the full pass): org-like clusters whose names are one once a corporate suffix (AI, Inc., Corp.,
   Corporation, Lab(s), Technologies, Holdings) goes merge `rule:corp_suffix` only when at least `suffix_min_posts`
   (2) posts name the bare org beside a thing the suffixed one makes (its stated maker or its parent), or the other
   way round; squashed-equal org clusters merge `rule:corp_squash` (the squash rule, which never saw a maker made for
   the hierarchy alone). Never two clusters of 2+ names (the chain guard's), never a pair Haiku called different,
   never the owner's apart. Without the posts nothing: the alias questions decide (a suffix alone is ambiguous).
5. `shown` (after the linking): each cluster's shown name and type on its root (`mx_entities.shown_name`,
   `shown_type`, `shown_by`): the member name the most distinct sources write as a span (then posts), not counting
   a span written as a handle nor one in a post by the account it names (the post's author, or its source's display
   name); for a person a full name holding the one-word name; the type that 75% of 5+ mentions give, or person over
   org when a person's full name is in it and a third of the mentions say person. One-name clusters: only the type,
   no query. The clusters the run touched (its posts' entities, merges and undos since) each run; every cluster on a
   full pass, resumable (`shown.after`). `name` and `type` stay what the entity was made as, and still decide identity.

Each repair is on or off in `entity_bands.json` `repairs`; counts in the run's `entities.repair` and `entities.shown`.

### Views
`entity_views._ent_view` shows a root's label and shown type, and the maker as the maker's cluster (`maker_id`, its
label) when the stated maker's name aliases one; family, versions, maker, published, surges and the rabbit hole show
labels; search shows `COALESCE(shown_name, name)`. Aliases still list every member's own name.

## Checked against the server's shapes (read-only GETs, 2026-11-11; not committed)
- Class 2: the org cluster [family, org, org+family name, org+suffix] has its family a version parent with a
  model-typed name and the "org+family" name ending in the family's name: the cut separates them unless the owner's
  answer is the crossing edge. One cluster (a model name the owner answered `same` with the org's suffixed name)
  is owner-made: it stays (`held`), and its versions keep the org cluster as their family until the owner undoes it.
- Class 3: the split families are `thing` entities (first written bare) that versions name as parent, so the family
  test reads version parents, not only `family` entities. The maker's family names share one brand word (5 names);
  the brand-prefixed and maker-prefixed families state shared versions; the maker-less "Cora"-style
  families each have a version already merged with the brand-prefixed one.
- Class 4: on the server the "<Co> AI" makers were already aliases of the "<Co>" clusters; what showed split was the
  stated maker string (now the org's label).
- Not fixed: a bare variant name ("Mira", with "Zentra Mira") beside a version's variant ("Zentra-6 Mira"): another
  granularity (a variant line across versions), not a family prefix; left to the alias questions.

## Not measured (say so before relying on it)
- `corp_suffix`'s precision: no labelled set; the open queue holds ~45 suffix-equal org pairs Haiku called `same`
  below the bar (several plausibly different: a common word with and without "Labs" or "AI"). The rule needs
  2 posts of maker evidence, and is one switch off.
- `merge_versions` runs on every family cluster of 2+ family names, not only those this repair joined.
- The repairs' time on the server (~31k entities in 30 days, more overall): Python over the book plus bounded writes;
  the stage's last full run took 44.6 s of its 45 s budget, so the repairs (first, 25% share, each step skipped past
  it) shorten what the linking does in that run; the stage is resumable.

## The alias question supply (proposal, not built)
The server's last full run: pool 11,163 pairs (str 6,935, emb 2,756, family 1,201, answered 1,119, maker 149);
decisions: ask 5,743 (waiting), apart:judge 3,143, apart:version 1,187, apart:family 429, auto 57 (Haiku 29); asked
anew 1,452 (by str 4,578 / emb 1,495 of the asks). Haiku's `same` merges are ~1% of what it answers. Pre-filters to
measure on the 139k answered alias questions (mx_tasks kind alias + mx_calls relation/confidence), each scored as
(asks removed, `same` >= 0.9 lost, owner-confirmed merges lost):
1. both names in one post each (one mention): likely low `same` rate and low value even when same;
2. a type conflict at the cluster level (org/person vs model/product/place): a `same` there is never automatic
   (it only feeds the queue's `type` items, which the owner does answer `same` ~30 times): ask only when one side
   has 3+ posts;
3. string pairs by trigram Jaccard bucket (0.5-0.6, 0.6-0.7, ...) and word containment where the longer adds a
   version or a product word: raise the bar where the `same` rate is < 1%;
4. vector-only pairs by cosine bucket (0.80-0.85 ...);
5. never re-pool a pair Haiku answered `different` at >= 0.9 unless one side gained a name (today the answer is
   re-read each run, which costs decisions, not questions).
Measure each as a dry-run over the answered set; adopt only those losing no owner-confirmed merge.

## Tests
`insight_core/tests/test_markx_entity_fixes.py` (invented names): the guards (no database: the org-family guard incl.
Haiku `same` and two orgs sharing a word; the family_version rule incl. another version and another maker; the
shown name and type), and the stage on a test database: (1) the account's own posts and handles not counted, a
person's full name and type, the owner's rename kept; (2) a family merged into an org cut by an undo, the owner's
merge kept and re-pointed, nothing deleted, not re-merged by the next full pass; an owner-held cluster left; a version
named by its maker's name gets a family under the org, old data reparented and logged, idempotent; (3) brand and maker
prefixes joined with evidence, another maker never, two prefixes without a shared version never, another version
never, a new version merged by the rule, the owner's undo of a family merge respected; (4) a suffix pair joined with
posts, not without, an owner's apart answer respected, the maker shown as the org.
