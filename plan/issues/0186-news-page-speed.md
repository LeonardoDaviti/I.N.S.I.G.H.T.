# 0186 — The News page's speed (v10.17)

Status: **built** (branch `v1017-news-speed` from v1016 4e9da6a; the News part also as the hotfix v10.16.1, branch
`v10161-news-speed` from main 2cd62c2). Not merged, not pushed, not deployed. Migrations **0127** (in both) and
**0128** (v10.17 only).

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

## The same class elsewhere (v10.17, after the hotfix)

**The entity page** (`/api/markx/entities/{id}`, ~12 s on the server) read the whole book (with every mention
counted) and walked it, and read every current mention once more (`named_now`, 830k rows on the server). Now on a
page's book, which also answers, for the entities asked, their mention counts (types, subject), whether a version
names them, their versions and families, the aliases leading to a cluster (`alias_keys`), the entities under a
cluster (`with_parent_in`) and those of a squashed key (`by_squashed_key`, 0127's index). The walks became those
questions: the cluster (`_members`, entity_addresses), the versions under a family (the page and the timeline), the
maker candidates, person_page.entity_keys, components_of. `named_now` on a page's book answers per root (its
cluster's current mentions and pins, the publishers' names through migration **0128**'s index).

**Discover's main source** (17-20 s per stale cache) reads a page's book; its cache key is now what the list is
made of (`pick` / `picked_stamp`: the announced stories of its window with their members, types and origins, the
readings and entity answers of their members, the sources): a read-v3 answer of a post in no announced story (the
worker's steady stream) no longer drops it.

| route (the copy) | before | after |
|---|---|---|
| entity page, 45 entities (real and synthetic, merged ids, versions, persons, a missing id) | median 5.08 s, total 340 s, peak RSS 921 MiB, 45 whole-book reads | median 0.28-0.32 s, total 36-52 s, 404 MiB, none |
| Discover main source, one scan | 11-18 s (under load), 594 MiB | 7.6-8.0 s, 223 MiB |

Every entity page's JSON and the main source's answer are byte-identical before and after. The slowest entity page
left is a synthetic entity named in ~25k posts: its own posts' lines, not the book. Main source's remaining time is
the code steps (perspectives.Story) of the ~2,000 announced stories of its window, now only when they change.

## The class closed: no API request reads the whole book

The rest of the requests that read it: the post page's panel (its subjects' timelines, `timeline.before_post`, and
`post_entities`), the story page (`built.build`), the entity queue (`entity_views.queue`, with `named_now` asked for
the open items' roots in one go), the owner's answers (the queue's `entity_answers.answer`, an entity's sources and
handles), research's first step (`held`: the cluster, the names around the seed's by `keys_around`, an entity of a
key by `first_with_key`; `channels_view`), and Discover's background build (`rabbit_hole.discover_rows`, the
originals' `plan_entities` and `plan_works`, whose "never a product's front page" asks the site word by the squash
index). `entity_addresses` reads clusters, never `book.members()` outside its stage.

**Every GET route on the copy** (the app's OpenAPI paths with real services, the copy read-only), before -> after:

| route | whole-book reads | seconds (a loaded machine) |
|---|---|---|
| /api/markx/news | 2 -> 0 | 10.6 -> 1.1 |
| /api/markx/stories/{id} | 1 -> 0 | 14.1 -> 0.03 |
| /api/markx/posts/{id} (two posts) | 2 -> 0 | 6.7 / 7.7 -> 0.10 / 0.21 |
| /api/markx/entities/{id} (three) | 1 -> 0 | 17.1 / 8.4 / 5.5 -> 1.7 / 0.37 / 0.22 |
| /api/markx/entities/queue | 1 -> 0 | 9.8 -> 0.04 |
| /api/discover/main-source | 1 -> 0 | 20.6 -> 12.3 (a stale cache; kept until its stories change) |

87 paths; every other answer byte-identical, but those that vary run to run by themselves (logs, uptime,
/api/markx/entities' tie, 0177). The owner's answers (16 queue answers, same and different, on 8 open items), an
entity's sources and handles, and research's first step on 9 seeds: identical with the generated ids and times
masked, the merges written identical. The harness process's peak (all GET routes) is the export's (7.5 GB, the
owner's export of everything, not the book).

**The guard** (`tests/test_api_no_whole_book.py`): every call of `identity.load_book`, and of `read_ents` without
ids, is in a job listed in `JOBS` (the decision run and its stages, the command line, 0165's measurement), read from
the source; and every GET route of the app over a seeded world (an entity with posts, a merge, a version, a News
row, a story, a queue item, a surge), the owner's entity answers and research's first step run with the whole
book's reads recorded: none. A new route or path that reads the whole book fails it. A page's book cannot be walked
(TypeError), so a request that tries fails loudly too.

## Left

- Discover's main source still builds the code steps of every announced story of its window (~2,000 on the copy,
  7 s) when they change; Discover's own list is built in the background (0172), now without the whole book.
- /api/markx/entities (the list) answers a tie by fetch order (0177): not changed.
