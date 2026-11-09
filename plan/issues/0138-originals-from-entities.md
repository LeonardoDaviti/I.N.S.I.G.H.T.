# 0138 — Originals from entities: a document or release that several voices are about, collected without a story; Discover learns from the originals it collects

Status: **spec** (2026-11-09). Stealth (Mark X's entities drive a Mark IX path). Builds on: 0123 (Collect originals:
the save path's reader, the credit, `story_originals`), 0113 (Discover's Pages tab), 0133 (ent-v4.2: documents,
`by`, the citation rule, `mx_mentions_now`), 0109 (Discover's not-sources rules), 0119 A (identity), 0101 (Discover
with Mark X).

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; 0123 whole; 0133 §2–§5; 0113 "Changed by the measure".

**The owner (2026-11-09):** "why can't discover suggest and save automatically such linked originals or other types
of mentioning. our discover should be self-improving and self-downloadable to always increase our reach."

**Constraints:**
- every request goes through the existing paths: the save path's reader under the host's gate, 0123's credit
  (`originals_rules.credit_after`), backoff; tests stub every request; download nothing from the development machine;
- never a walled page, never store an access token (0123's rules, unchanged);
- no real names in committed files (private rows in `plan/research/0138-notes.md`); fix the class, never a site;
- keep everything; nothing merges unless `scripts/realdata-check.sh` passes;
- the owner's testing rule: 3–5 real checks, not a long measure; publish to the server and check there.

## Why (the owner's case, 2026-11-09; rows in the private notes)
- Two posts of two voices, 70 hours apart, both read by ent-v4.2 with the same paper as their **subject** (role
  `subject`, type `document`, `by` its two authors). The entity page joins them: 2 posts, 2 voices.
- One post links the paper's page (an arXiv abstract), its code and a demo; the other links nothing but itself.
- **Nothing fetched the paper:** both posts are loose (no story), and every automatic path starts from a story:
  - Collect originals (0123, **on** on the server) collects only the root of a News row's main story;
  - Discover's Pages (0113) lists only story roots;
  - Discover's Sources never suggests a paper host (0109: "papers stay in stories and Classics");
  - 0133 put "fetching linked documents so they become stored posts" out of scope.
- So INSIGHT knows *what* the original is (the entity) and often *where* it is (a post's link), and nothing joins
  the two.

## What it does

### A. An entity's address (no request)
For an entity of a type that names one thing (`SPECIFIC_TYPES`: model, product, software, document, dataset), its
**addresses** are the links its posts carry that are that thing's page, found by rules in this order:
1. **Identifiers:** a post that names the entity and holds an arXiv id or DOI link (0133's citation rule hit) — the
   rule hit and Haiku's document are one entity (0133 §3's merge); the address is the paper's abstract page.
2. **Title match:** a link in the post whose read title (0113's rule 8: the page's title, else the link's text)
   matches the entity's name or alias by identity's name key.
3. **The maker's own page:** for a model / product / software entity whose maker is an entity with a followed or
   known site (`published` link, 0133), a link on that site named by 2 rules above. Never a front page (`is_home`).
- One entity, at most one address per kind (paper page, code repository, demo, release page); the paper or release
  page is the **original**, the others are kept as its links.
- Stored in a new table `mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at)`, written by the
  entity stage incrementally, never deleted. Redirected entities (merges) read their target's.

### B. Collect an entity's original (Collect originals, extended)
When Collect originals is on, after the story job (same hook as 0123), also:
1. **The trigger:** an entity with an original address, not stored (no post at the address, normalised as
   `/api/saved` does), that is the `subject` of posts from **2+ voices** within the last 7 days — or **1 voice** when
   that post is a News lead. Roles `source` and `recommended` alone never trigger (0133: they are evidence, not news).
2. **Order:** shares 0123's credit and queue; News story roots first (0123 unchanged), then entities by voices, then
   newest. Recorded once in `story_originals` with kind **`entity`** (the entity id in a new nullable column), never
   asked again.
3. **0123's kinds apply:** followed → 0114's fetch; walled / no-article → recorded, not asked; a tweet → from a quote.
   A **paper page** is an article for this path (today `paper_address` is not excluded; keep it so, add a test).
4. **Where it lands:** the save path stores it as a collected original (`· collected original`), Mark X reads it
   like any post (read, entities), and the entity page shows it first as **"Original"**. If its posts are in a
   story, it joins by 0113's rule as the root.
5. **The credit:** if entity originals wait more than 72 hours on the credit, the cap rises from 3 to 6 (measure the
   queue's wait first; report it).

### C. Originals with no link (a lookup, its own switch)
For a `document` entity that is the subject of 2+ voices and has **no** address after A (the second post's case
alone):
- one **lookup request** by title: the arXiv API's title search (`export.arxiv.org/api/query?search_query=ti:…`,
  max 3 results), else Crossref by title for a DOI; a match only when the returned title equals the entity's name by
  the name key and an author from `by` is in the authors. Else recorded `not_found`.
- A new switch **"Look up unlinked originals"** next to Collect originals (`system_settings.scheduler_config.
  lookup_originals`), **default off**; one credit per lookup, plus one per page fetched. The owner turns it on after
  seeing the measure.

### D. Discover learns from originals (self-improving reach)
1. **Pages tab:** lists entity originals not stored (A's addresses meeting B1's trigger) beside story roots, with
   the entity's name and its voices; "Save" works as today. Collected ones disappear by themselves.
2. **Sources that supply originals:** for each site (by Discover's address key), count the originals of B and
   0123 it was the address of, and the posts of yours that **linked** those originals first (the summariser sites).
   A site with **3+ originals in 30 days** that you don't follow becomes a Sources suggestion with the reason
   "the original of N things your sources talked about", through the feed finder and page watching (the
   source-adding rule). Paper hosts stay no suggestion (0109); a summariser site of papers can be one.
3. **Which suggestions worked:** a source followed from D2 records the follow date; Discover's row later shows how
   many originals it brought **before** any other source of yours (`first_seen`, 0137). Shown, not used to rank yet.

## Not in this issue
- Following a source automatically (stays the owner's tap).
- Searching the web for unknown entities' originals beyond C's two lookups.
- A document's own reader (0133).

## Measure (3–5 real checks; on the server copy by GET or after deploy)
1. A's addresses per 1,000 entities with 2+ voices, by rule; 20 sampled right / wrong (private rows).
2. B's triggers a day and the credit's wait; how many collected land on the right entity.
3. The owner's case: the paper is collected and shows as the entity's Original.
4. C (if switched on): found / not_found on 20 unlinked documents.

## Done when
- Tests (stubbed requests): A's three rules and their order, merges read the target, `is_home` never an address;
  B's trigger (2 voices, 1 voice News lead, roles source/recommended excluded), its order after 0123, recorded once,
  a paper page collectable; C's match rule (title key + author) and its switch off by default; D1's rows, D2's 3+
  threshold through the feed finder, paper hosts excluded.
- Migration for `mx_entity_addresses`, `story_originals.entity_id`, the switch default.
- `realdata-check.sh` passes; the frontend builds; design docs claim any new UI.
