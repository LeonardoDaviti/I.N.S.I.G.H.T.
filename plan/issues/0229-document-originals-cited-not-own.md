# 0229: An entity's Original is its own page, never a page its posts cite (Stealth v10.25, slice D)

Status: **built, not measured blind**. Backlog 0225 #26 and #27 (the Original half). Migration 0159. Branch
`worktree-agent-a095ed3b9c559dc23`. Private rows: the main checkout's `plan/research/v1025/d/` (gitignored).

## What was wrong
The address rules (0138 A, `utils/entity_originals.py`, run by `markx/entity_addresses.found_in_post`) took a match as
evidence that a page IS the entity, when a match shows only that the post CITES it:
- **Rule 1 (`identifier`)**: a document that is its post's only document took the one paper the post links as its own
  paper. A report's posts link a paper the report cites, and a filing's posts link a paper the company wrote, so
  #26's two documents got those papers as their Original. The paper (`kind = paper`) also outranked the filing's own
  page, which rule 2 had found (`original_of`: paper before release).
- **Rule 2 (`title`)**: any page whose read title is a model's name was its release page. In #27 that was a third
  party's dashboard titled with the model's name. On the copy it also took encyclopedia articles, pastebins, store
  listings, a router's model page and forum posts.

## What changed (the module that owns the decision)
- `entity_originals` (the rules), new kind **`cited`**: a page the posts cite. It is never an original, an address, a
  work or a site, because `pick` skips it and every reader that filters on kind leaves it out with no change.
  - `paper_is_its_own`: rule 1's paper is the entity's own when the mention carries the id itself (its ref, or an id
    in its span or name). Otherwise its read title decides, and failing that the link's own words (`link_names`).
    Either must name the entity, by the title keys, the head before a colon, or a run of its name's words. Some link
    words are no evidence: a bare address, an id, page-kind labels (`LINK_LABELS`: "Paper", "[link]", "статья") and
    author-year citations. With no evidence, 0138's rule stands and the paper is its own (measured: most such posts
    are about that one paper). The code and demo links that come with a cited paper are cited too.
  - `own_site`: rule 2's release page of a model, product or software is its own only on one of three kinds of site:
    - its own site or its maker's: a host label, the site word or the whole registrable address run together that
      matches its name or maker, one of their words, or the maker's initials;
    - a model hub;
    - a code host.

    A document's page titled with its name is still the document (a filing on a regulator's site).
- `entity_addresses.stage`: the row's kind follows the posts that gave it, and `first_at` is kept.
  - A row an older rule wrote as the entity's own becomes `cited` when its post, read again, gives it as cited.
  - A post that gives it as the entity's own turns a cited row back.
  - Only rows whose post the run reads are rewritten. The counts gain `changed`.
  - `page()` returns the picked addresses and the cited list from one read; `of_root` is its first half.
- `scripts/repair_0229.py`: the same sweep (`EA.stage`, full), one chunk a transaction. The server's rows are fixed by
  it, or by the next full pass's addresses sweep. On the server that sweep has not started since 11-11 (0221), so
  **run the repair after the deploy**.
- **The page** (minimal edits in other slices' files):
  - `entity_views.original` (slice G) adds `cited` ([{url, kind, rule}]) from the same read. There is no new path and
    no new query.
  - `MarkXEntityPage.tsx` `Original` (slice H's file) says "No original page found yet." when there is none, and lists
    "Cited · what its posts cite, not its own page" below.

## The three cases (server pages, read-only GETs before the owner's stop)
- #26, the report: its paper is a stored post whose title names another work, so it becomes cited and the report
  has **no Original**. **The Anthropic blog post is not stored**: a search for its title finds only the posts that
  cite it (one of the report's posts, checked, links it). Its address is in the private notes. No row records it as the
  report's page: the posts' link words and read title would have to name the report, and nothing showed they do. Not
  verified on the server's rows.
- #26, the filing: its paper is stored with a title naming another work, so it becomes cited. The filing's own page
  (found by rule 2, on the regulator's site) becomes its Original.
- #27: the dashboard's host matches none of the model's or its maker's words, so it becomes cited. The model has no
  other own address on its page, so it shows no Original.
- **#27's stories: page order, not identity.** `entity_views._entity_page` sorts story blocks by voices, then newest,
  whatever the entity's role. The first block (19 voices) has one post that names the model `compared`; the first
  block with it as `subject` is the 4th, and its own release stories are the 18th, 21st and 25th. The fix is slice G's:
  sort blocks where the entity is subject or actor first. Not changed here.

## Measured (prep_mxreal clone: the server's posts to 11-05, ent-v3 mentions; proxy entity = type and name key)
- Before the scratch server was wiped, `found_in_post` ran over every mention of the specific types: 10,606
  mentions, 3,586 posts with links.
  - Before: 570 proxies had an Original.
  - After: 531. Changed: 41 (9 documents, 8 models, 14 products, 10 software).
  - Seconds 2.4 → 2.4-2.5; peak RSS 64-65 MB both.
  - Rows: identifier-paper 140 → 131 (10 cited); title-release 208 → 169 (39 cited).
- **My own unblinded reading of the 41 changes (not the bar's measurement):** about 37 are right and 4 wrong.
  - Wrong, documents: a paper linked under its other name, and a paper named in Russian (inflected).
  - Wrong, maker types: a maker's site under another brand's domain, and a person's site under a contraction of their
    name.
- **Not done (owner's stop, 2026-11-19 13:15 UTC: the scratch server was wiped, and there is no real data, no
  production requests and no labelling):**
  - the blind haiku labels of the frozen set (226 items: 200 random proxies plus the 41 changed; sha256
    `b699cb8e7c9ec412f90e285ed4e56d7df8e9f4eba674452903535f527666151f`, in the private notes; labelling was stopped
    before any label was written);
  - the before and after point estimate and Wilson LB;
  - the server-shaped clone (v1024srv_s1: its entities are synthetic, with no documents, so it could only time the
    sweep);
  - the real-data check.
- **Below the bar until measured:** the bar is point ≥ 97%, LB ≥ 90%. The change only removes or replaces Originals,
  so the risk is fewer Originals (and fewer collected), not a new wrong one.

## Tests
- `test_entity_originals`: rule 1 evidence (carried id, read title, colon head, link words, labels, author-year),
  `own_site`, `pick` skipping cited.
- On the database:
  - a report's cited paper, code and demo (no Original, listed as cited);
  - a third party's page titled with a model's name;
  - an old row demoted by the sweep and promoted back.
- Run together with `test_api_no_whole_book`, `test_markx_timeline`, `test_markx_research`, `test_official_0196` and
  `test_markx_storage`: 172 tests OK.
- Frontend: `entityOriginal.test.tsx` (5 OK) and `tsc --noEmit` clean.
