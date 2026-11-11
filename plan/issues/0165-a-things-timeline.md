# 0165 — A thing's timeline: earlier names, outside mentions, the launch (spec, not built)

Owner 2026-11-11, on a launch read in INSIGHT: "how the whole story and timeline looks like for it?" INSIGHT had
every post needed and could show none of the timeline. The real case (names, posts, dates) is in
`plan/research/0165-case.md`; the names below are invented.

## The case, as seen (read-only API, 2026-11-11)

A maker ("Vantor") launches an open-source tool "Vantor Snap" on its developer blog, the same hour as two sibling
launches at a conference, and its news site's round-up names it an hour later. The tool is not new: six months
earlier the same blog introduced it as an experimental part of Vantor's serving product, "Vantor Forge Snap".

What INSIGHT holds, from the posts already stored:

| When | Source | What | In INSIGHT's view |
|---|---|---|---|
| 2 years before | maker's dev blog | the open tool it builds on | not linked |
| −165 days | maker's dev blog | **birth**: "Forge Snap", experimental | filed under "Forge" (the parent product) |
| −22 days | an inference engine's blog (independent) | "what comes next: restore warm workers with Forge Snap" | filed under "Forge" |
| −19 days | maker's news site | a customer uses Forge Snap | filed under "Forge" |
| day 0 | maker's dev blog | **launch**: "Vantor Snap", renamed, open source | the entity's page: 2 posts |
| day 0 +1 h | maker's news site | conference round-up naming it | the entity's page |

What the owner sees: the launch post has 0 stories, 0 connections, an empty "before"; the entity page lists two
same-day posts from the maker. **No way to see the timeline in INSIGHT today.** The entity's stored code address is the
same repository the birth post links (`github.com/<maker-org>/snap`), so the join was one rule away.

## The four gaps (classes, not this case)

1. **A rename is not joined to the earlier name.** "Forge Snap" → "Snap" is one thing; nothing proposes it.
2. **A name inside a bigger product is swallowed by it.** "Forge Snap" is linked to "Forge" (a component's mentions
   read as its parent's), so the component has no entity, no page, no history.
3. **No story without independent voices** — correct (two maker posts are not a story); but the one independent voice
   is 3 weeks earlier, outside any story window.
4. **An entity with no story has no timeline.** The page lists loose posts by role, newest first; the earlier name, the
   outside mentions, the birth and the launch are not shown as one line.

## What to build

### A. Components get their own entity (identity)
A mention whose span is `<parent product> <name>` where `<name>` is a component or feature (the guide's reading says
so, or the post's subject is the component, not the parent) is linked to the component's own entity, with
`parent` = the product (the `thing` level the family logic already has). The parent's page lists its components; a
component's posts count on its own page and, read-only, under the parent's "components" block. Rule from the reading,
never a word list; measured on the lab's mentions of the 20 biggest products before the switch (how many mentions
move, sample 40 read by me).

### B. Renames proposed by shared evidence (identity → queue)
Two entities of the same maker, one older (its last post before the other's first, or overlapping by < 7 days), become
a **rename candidate** when one of:
- the same own address (0138 `mx_entity_addresses`: code repository, release page, docs page), normalized;
- one name contains the other's distinctive word and a post says so ("formerly", "renamed", "now called",
  "previously known as", or the guide's reading marks the relation);
- the new post's text names the old name (the launch post names its prototype).

A candidate is a **question** (`rename`, a new queue kind): Haiku judges with both entities' first and last posts;
`same thing, renamed` merges as a redirect with `kind = 'rename'` (the old name stays an alias, shown as "earlier
name"); `different` keeps them apart for good. Automatic only after measurement (a band like 0130's), never at build.
The version guard holds (a version bump is not a rename). Owner's answers win, as in 0164.

### C. The timeline on the entity page (view)
Every entity page gets a **Timeline** block above the loose posts when it has ≥ 2 dated events, built read-only
from what is stored:
- **first seen** (the oldest post naming it or any earlier name),
- **earlier names** (rename merges) with their first and last posts,
- **releases** (posts whose role is subject, from the maker or its own address; versions for a family),
- **outside mentions**: posts by sources not the maker's, grouped by month, the first one marked,
- **stories** it is in (Mark X and IX), at their dates,
- **later developments** (0163 rows) and **back in the news** events.

Each line: date, source, title, why it is on the line (birth / rename / release / outside / story / later). Collapsed to
the 8 most important by default (birth, renames, releases, first outside, stories), "all" opens the rest.

### D. The post page: "before" from the entity's timeline
A post whose subject has a timeline shows its subject's previous events (up to 3: birth, last release, first outside
mention) in the post page's "before" section, which is empty for a launch today.

## Measure (before and after, on the lab / a fresh dump)
- **Renames:** candidates found, Haiku `same thing, renamed` precision on 40 read by me, and the ones missed (sample
  the maker's products with an address shared by two entities).
- **Components:** mentions moved, 40 read; the parent's page still right.
- **Timelines:** for the 30 biggest products of the last 30 days and 20 random ones: does the timeline tell the
  thing's history (my read, pass/fail per entity, the failures listed with exact rows, per [[report-breakage-format]]).
- Check cases in `plan/research/lab/cases.json`: this case (the launch's entity has its earlier name, its timeline
  starts at the birth post and holds the independent mention), plus two renames and one non-rename (a successor
  product with a new address).

## Not in scope
Fetching anything new for the timeline (only stored posts); predictions; a timeline for persons (later, with 0091).

## Slices (separate files)
- A + B: `markx/identity.py`, `markx/rename.py` (new), the queue kind, a migration (`mx_entity_redirects.kind`).
- C + D: `markx/timeline.py` (new), `entity_views.py`, the post page API, `MarkXEntity.tsx` / the post page.
