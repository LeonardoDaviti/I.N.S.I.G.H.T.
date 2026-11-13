# 0186 — The News page's speed (v10.17)

Status: **built** (branch `v1017-news-speed` from v1016 4e9da6a). Not merged, not pushed, not deployed. Migration
**0127**.

## The problem (the server, main 2cd62c2 = v10.16, 2026-11-13)

`GET /api/markx/news` took 19-22 s on every load (`/api/markx/overview` ~1 s, `/api/feed` 0.08 s). Timed read-only
from outside every ~3.5 minutes for 35 minutes: News 20-25 s at best (19.8, 20.8, 21.0, 22.2, 24.1, 25.0), 31-63 s
while a decision run was writing (the overview slowed with it then); it never went under ~20 s, so it was not
contention. `GET /api/discover/main-source` took 17-20 s whenever its cache was stale (0.04-0.15 s when kept).

## Where the time went (measured, not guessed)

A server-sized scratch copy: the 11-05 server copy (real Mark X rows: 380 stories, 8.8k entities) migrated to 0122,
its posts cloned to 148k, a year of synthetic stories (47k, every post a member), read-v3 types on a third of the
last 120 days, 250k more entities with 300k aliases and 760k mentions, 4,000 current surges, ~930k tasks and calls,
22k story connections, and a News run of 373 rows (160 SAME, 100 CHANGED, 113 NEW; 307 Mark IX rows, 3 gone) with
300 older runs' rows kept. `news.page()` timed per call (wrappers, cProfile), the same snapshot before and after:

| call | seconds (copy) | what it read |
|---|---|---|
| built.annotate (how each row's story is built) | 6.2 | |
| - identity.load_book | 1.8 | the whole entity book with every mention counted (GROUP BY over all mentions) |
| - perspectives.Makers | 1.4 | an index of every entity's and alias's squashed name, to find a story's maker |
| - came_true over the window | ~1 | every typed story within 30 days either side of the rows (thousands), their subjects, every leak x release pair, though only a judged connection can link one (SUBJECT_LINKS off) |
| - load_members, Story | ~1 | the rows' own stories (needed) |
| entity_views.surging_posts | 1.9 | the whole book again, to name ~200 surging entities |
| everything else (rows, posts, why, checks, headlines, folds, sections, flags) | < 0.3 | |
| **total** | **8.2** | peak RSS of the process 546 MiB |

Every other call is already bounded by the rows (repo.task_for and the other lookups are indexed). The server's
book is richer than the copy's (real makers, versions and fields, more merges) and its CPU slower: the same two
whole-book reads and the window walk are its ~20 s. main (v10.16) and v1016 measured the same (8.18 / 8.27 s).

**The class:** a page request reading the whole entity book (250k entities) and walking a window of every story to
answer a few hundred rows. The same read is behind the post page's panel (`post_entities`), the entity page and
Discover's main source (below).

## What was built

1. **A page's book** (`identity.lazy_book`, `LazyBook`): the merges and pins read whole (they are few), each entity
   and alias read when first asked (by id, by key; `prime` reads many in one query) and kept for the request. It
   answers what the whole book answers by id and key (root, label, by_key, cluster) and cannot be walked: iterating
   its entities or aliases raises TypeError, so a caller that needs the whole book must say so (`load_book`).
2. **The maker's names through the book** (`Book.name_forms`, `Book.maker_roots`): `perspectives.Makers` no longer
   builds its own index of every name; it asks the book which clusters a squashed form names and what a cluster's
   names are. The whole book answers from memory as before (the same snapshot, the same index, for the decision
   run); a page's book asks Postgres by the form. Migration **0127**: indexes on `names.SQUASH_SQL` (squash in SQL;
   Postgres and Python agree on every code point 1-200,000 and on every key of the copy, measured).
3. **"Came true" reads the connected stories.** With SUBJECT_LINKS off a leak story is linked to a release only by a
   judged connection, so `built.build` reads only the window's typed stories connected to the viewed ones (and no
   subjects); with SUBJECT_LINKS on it reads the whole window as before.
4. `entity_views.surging_posts` and `post_entities` read a page's book.

## Before and after (the same copy, back to back)

| | before | after |
|---|---|---|
| news.page() | 8.21 s, 48 queries | 1.32-1.96 s, ~560 queries (one a name or owner asked, ~1 ms) |
| peak RSS of the process for the call | 546 MiB | 74 MiB |
| built.build over 669 stories (380 real, 289 synthetic) | 9.2-11.2 s | 1.8-2.0 s |

**Equivalence.** The page's JSON is byte-identical before and after (213 rows, 16 "came true" links, 213 surging
rows, 35 removed lines, 3 gone rows), and `built.build` over every real story of the copy plus 300 synthetic ones
is identical (577 built, 337 stories with a maker found through the names, 3 links), the stories' makers, codes and
duplicates included. Tests: the page's book answers as the whole book (roots, labels, keys, clusters, makers' names,
owners, ancestors), it cannot be walked, squash is the same in Postgres, the News page never reads the whole book
and reads the same entity rows with 20 or 2,020 more entities in the book, and an unconnected typed story of the
window is no longer read.

What is left of the page's time is the rows' own work (the Story code steps over their members' texts), which grows
with the rows, not with the book or the window.

## Left (the same class, not changed here)

- **The entity page** (`/api/markx/entities/{id}`, ~12 s on the server) reads the whole book and walks it: its
  members by a scan of every entity (`_members`), the versions under a family (every entity), the maker candidates
  (every root's squashed key), `person_page.entity_keys` (every alias) and `entity_addresses` (`_names`,
  `book.members()`). Each has a bounded form now (`cluster`, the parent index, migration 0127's squash index,
  `name_forms`); converting them needs the entity page's own equivalence check.
- **Discover's main source** (`/api/discover/main-source`, 17-20 s per stale cache): on the copy 10.5 s, of which
  the whole book 1.8 s and the names' index 1.3 s, and 5 s building the code steps (`perspectives.Story`) of every
  announced story of its window. It needs the whole book for the addresses (`entity_addresses.current`). Its cache
  is dropped whenever a read-v3 answer lands (`_stamp` counts them), so with the worker running it is rebuilt on
  almost every open.
