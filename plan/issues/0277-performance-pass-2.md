# 0277 — Performance pass 2: the entity page's bytes, the planners' scan, the post-load N+1, search

Status: **built in part** (Stealth v10.33), not deployed. Follows 0270 (its open items 2, 7 and 12).

## 1. The entity page: 2.5 MB a default answer (built)

### Measured (production, GET only, 2026-11-21, from this machine)

GET /api/markx/entities/7244a712-e918-4cba-b834-8c837deda730 (Anthropic), timed twice after 0270's 13.1 s / 11.4 s:
**0.45 s, then 0.26 s, 2,512,657 bytes**. The page was kept this time, so the 11-13 s of 0270 were builds
(`kept_full` → `_full`: the stamp moved, i.e. a new decision run, an owner mark or a new current mention of the
cluster), not the kept answer. The answer itself, by key (bytes of each value's JSON, from that production body):

| key | bytes | what |
|---|---|---|
| citing | 1,119,088 | 1,053 posts citing it as evidence, each with its mention context |
| stories | 1,056,010 | 50 story blocks with **all** their posts: 1,527 post lines |
| timeline | 302,257 | 920 events, of which the page shows 8 (`top`) until "All" |
| rabbit_hole | 150,360 | 863 works |
| loose | 135,277 | 100 loose posts |
| published | 104,111 | the same 863 works |
| relations | 73,387 | 368 relations |
| surges | 68,412 | 31 days, each with its `post_ids` (read by no view) |
| versions, sources, brief, ... | < 40,000 each | |

### Fix (markx/entity_views.py, the module that owns the page's cut; markx/api.py the route)

The one kept page (`_full`, built at the caps) is unchanged; each request's cut (`_cut`) now also cuts the long
lists unless `?all=true` (`_short`): each story's posts to 6 (its original first, then the posts about the entity,
shown in the block's order; `posts_total`), the citing / recommending posts to 20 and the works (published, the
rabbit hole's) to 30 (`<list>_total`; the rabbit hole's `missing` counts every work not stored), the relations to the
60 most stated (`relations_total`), the surges without `post_ids`, the timeline to its top events (`items_all`).
The route's defaults are 20 stories and 30 loose posts (were 50 and 100; "Show more" asks 20 / 30 more).

Frontend (MarkXEntityPage, MarkXTimeline, services): a story shows "N posts" from `posts_total` and an "All N posts
of this story" link; citing, recommending, published and links show their totals and an "All N" link; the
timeline's "All N events" asks the whole page; "Go down the rabbit hole" reads the whole page's works first when the
answer lists only some (it collects every work not stored, as before). Every "All" link is one `?all=true` request
(the page as before, 2.5 MB for Anthropic), cut from the same kept bytes: nothing built again.

### Measured after (the production body above, cut locally by the new `_short` at the new defaults)

| | bytes | cut time |
|---|---|---|
| before (default answer) | 2,512,657 | |
| after (default answer) | **260,598** | 0.3 ms (on the decoded JSON; the decode/encode of the kept bytes was there before) |

Largest left: stories 92 kB (20 blocks), versions 36 kB, surges 27 kB, sources 27 kB, loose 23 kB, citing 20 kB.

No PAGE_SHAPE bump: the kept bytes keep their shape; the new fields are added by the request's cut, so a page kept
by the previous code is answered in the new shape (TheShapesAreNamed records the answer's new hash under shape 4).
No added memory: the cut works on the decoded kept page the request already held, and answers less.

### Open: the build (11-13 s on production for Anthropic)

Not profiled here: a production-scale synthetic world for `_entity_page` (mentions, handles, both story layers,
timeline, relations, documents, contexts, brief) did not fit this pass. The kept page hides it except after a stamp
move; for a big entity the stamp moves with every new current mention of the cluster (`page_inputs`: count and
newest `mx_mention_sets.at`), i.e. often while the worker runs. Next: time each part of `_entity_page` on the server
(the jobs process logs a kept page's `seconds`; add the parts there) before changing it, then the candidates are
`_documents` (it builds 1,053 citing lines with contexts of which 20 are now shown), `TL.of_entity` (920 events for
8 shown), `_with_contexts` (a context for every post line) and the stamp's mention part (the page could read the
mentions as of the last decision run, as the docstring already says for the worker's other answers).

## 2. The planners' posts-by-age scan, 3. load_posts' N+1, 4. search

See the sections below (items 2 and 3 were built in a parallel slice).

Item 4, search, measured only (production GET, 2026-11-21): /api/search?q=openai 1.19 s, then 0.37, 0.37 s (41 kB);
/api/search?q=gemma%20release 5.00 s, then 0.69 s (60 kB). A new query is 1-5 s and the same one again 0.4-0.7 s:
the cold cost is per query (its text's first planning and reads, or a query vector), not per process. Not profiled
in this pass; next: split one cold query's time between the text search, the vector and the result build.

## Tests

- backend: test_markx_kept_pages (the default answer's cut; ?all=true answers every list, the limits clamped and cut
  from one kept page as before), test_markx_entities, test_markx_story_window: 111 tests OK.
- frontend: tsc; vitest personPage, handles, entityOriginal, flagsAndContext, entv4, entities, timeline: 33 OK.
