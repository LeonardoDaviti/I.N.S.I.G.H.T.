# 0162 Built: research

Built 2026-11-12 on branch `scout-research` (Stealth v10.14), after 0148 (same branch). **Migration 0107**
(`mx_research_runs`, `mx_research_findings`, `mx_research_pairs`; `mx_scout_runs.research_id`;
`mx_source_provenance.kind` may be `research`; `mx_tasks.subject_kind` may be `research_pair`). Mark X tables only, no
key to a Mark IX table; the owner's Follow and Watch this add a source and a track as Sources does. Not measured on
real data yet (see "Measure"); private rows go to `plan/research/0162-notes.md`.

Owner decisions applied: (1) the paper index is a free open one first, **OpenAlex**, behind the setting
`research_paper_index` (`openalex` | `off`; a keyed index is a new class later); (2) **Research this never runs by
itself**: a run starts only on the owner's tap (the ingestion hook only advances runs the owner started, in their
first 30 days). From the owner's real tests: a **web-search step** for accounts a site doesn't declare, a pluggable
provider behind a setting, off when unconfigured.

realdata-check: run at release (not run here).

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | A research run | `markx/research.py` `start`: the seed's kind (`seed_kind`: an entity id; a link; a pasted post = text with links or long; a question = asks or 6+ words; else a name), a run row and its scout run (0148, trigger `research`), step 1 at once. `POST /api/markx/research {seed, kind?}` (`markx/research_api.py`), its outside steps in the background; `GET /api/markx/research/{id}` the page (advanced in the background when it can go on); `POST .../rerun` (a new run of the seed; a finding an earlier run of the seed or entity found is not `new`). Entry points: **Research this** on the entity page, `Research “<words>”` on a search, and in a post's Mark X panel (each opens `/research?seed=…`). |
| 2 | Step 1, what INSIGHT has (no request) | `held`: a name by identity's key or its aliases, then search's entity cards (exact key); a question's entity cards (up to 3; 0141's meaning search is not built, see Open); a link's or post's entities by their addresses under every version. Each entity: posts, stories, voices, addresses (with the maker candidate the platform states), its newest posts; the posts linking any version of the seed's or its addresses (`research_web.versions`: arXiv abs / html / pdf / vN / its DOI; a project's page and everything under it). Names whose key holds the seed's whole are offered as maybe one thing (never merged here: identity's review queue does); an unknown name is proposed as new. |
| 2b | The same announcement elsewhere | `same_post`: each link of a pasted post resolved (one request, a shortener lands elsewhere), the posts holding a **unique** one (held by at most 10 posts, never a front page, an account or a site); then a near-copy of the pasted text (Mark X's copy rule, `tasks.near_copy`, over the last 30 days' posts its rarest words find); `around`: the posts of the maker's own followed channels within 3 days. Each hit says why (`shares the link …`, `a near-copy of its text`). The pasted post is not embedded on the fly (no embedder on the server): text shingles stand in. |
| 3 | The maker and the identity graph | `research_web.classify` (platform classes only: paper ids; X / YouTube / Reddit / Telegram accounts; code hosts', model hubs' and package indexes' accounts and projects, from entity_originals' vocabularies; a site or a site's one-segment section; never an article or a post). Hop 0: the seed's things (the link; a post's project and paper links; an entity's addresses), `same: seed`. Hop 1: the owner a platform states for a project page (`<host>/<owner>/<thing>`): `yes` by the rule "the platform says this account owns it", no request. Each page read once (`page_summary`: title, description, text, declared links rel=me first, @handles), at most 60 page requests a run; only a confirmed page's declared links are followed, at most 2 hops; never another site's article, a post, a share or login link, nor the platform's own menus. Same identity by rules first (`same_identity`: the platform's owner; each links the other; the same handle and one links the other; its profile links or names the confirmed one); else one `identity` question (kind `identity`, guide `identity-v1`, subject `research_pair`, schema `{same: yes / no / unsure, confidence, why}`, `validate._identity`: `why` one line), at most 20 a run, the answer applied by `research.after_identity` (from `tasks.record`): a yes follows its links next. A name alone never makes a yes. |
| 3+ | Web search (owner) | `research_web.web_search`: `INSIGHT_WEB_SEARCH=searxng` with `INSIGHT_WEB_SEARCH_URL` (a SearXNG instance's JSON API) or `brave` with `INSIGHT_WEB_SEARCH_KEY` (Brave's API; the key from the environment only, sent as a header, never stored or logged); off when unset. Queries: the maker's name (identity's maker of the seed entity, a person or org seed's name, confirmed handles, a name seed) alone and on each platform class INSIGHT reads (`site:` of the class's own host); at most 5 a run. Each result an address read and judged as in 3 (never an identity by its name: a namesake is asked, `no` keeps it out). `GET /api/markx/research/settings` says which provider is on. |
| 4 | Channels | `channel_candidates`: every confirmed account, project, site or community a candidate of the run's scout run (finder `research`, keyed by the identity graph's key, so a project and its owner's account are two channels), test-read by 0148's reader (the add path: the feed finder and page watching, or a source kind) into the scratch area, health and cadence; fit by the track judge once the run has a track. Follow: `POST /api/markx/research/{id}/channels/{c}/follow` (0148's `follow`: active into the watched track, else passive; provenance kind `research`); Not this one. |
| 5 | Papers and discussion | `research_web.OpenAlex` (paper_index): the work by its exact DOI or arXiv DOI (a record whose id is not the one asked is refused), its references (`cited_by:`), citing papers (`cites:`), its authors' newer papers kept only when they share 2+ authors, or an author and the field (the index merges namesakes); each reference held or not by every version of its address (`held_refs`); the authors listed with the index's own ids. At most 4 calls a paper (spec: 2; see Open), 2 seed papers a run. Discussion: the search feeds of the platform classes INSIGHT reads (Reddit's, the Hacker News class's, X through the configured bridge) for the exact id, a project's owner/name, or the paper's exact title; a hit must contain the id as a whole token (2606.13843 is not 2406.13843), link a seed address, or carry the exact title (`exact_hit`); at most 6 searches a run. |
| 6 | What the owner gets | `research.view` / `pages/ResearchPage.tsx` (`/research/:runId?`, its own chunk): In INSIGHT · The same announcement elsewhere · The maker (confirmed accounts with their rule, `Not sure yet`, `Not the maker`, and "These are <name>: yes / no" for a person or org INSIGHT knows, 0144 B's answer) · Channels to follow (0148's rows; Follow / Not this one) · Papers (references held / not held, citing, newer) · Discussion found · What could not be read and why. **Watch this** (`research.watch`): a track (0145) named for the seed, described by it and its maker, its active sources the channels followed from the run (their provenance moved to it), up to 5 of the seed's posts its first ✓; the run's channels are then judged by it. |
| 7 | Cost guard | Per run: 60 page requests (identity graph and shorteners), the scout run's 40 test reads and 800 judgements, 4 paper-index calls a paper, 20 `identity` questions, 5 web searches, 6 discussion searches; spent on the run row and in `stats.spent`, and the log. A run is claimed (`busy_until`) by whoever advances it. With `INSIGHT_DISCOVER_READS=0` nothing outside is asked. |

Worker: `identity` in `DEFAULT_KINDS` (after `scout`, before `track`), `PER_CALL identity=5`. Design: `pages/shell.md`
(Research), `system/information-architecture.md`. The frontend bundle baseline is updated (`bundle-baseline.json`): main
already sat at +0.97% of it and the research route adds 72 bytes gzip to the index chunk (+1.01%).

## Tests

- `test_markx_research` (23, every request stubbed): each seed kind; the `identity` kind, guide, schema and validation;
  `classify` by platform class (a post and an article are no identity); declared links (no menu, no one else's post,
  rel=me first); the same-identity rules (the platform's owner, both ways, the same handle, the page names the other; a
  namesake and an unreadable page unclear); every version of an address; exact discussion hits; OpenAlex by exact ids
  with the namesake's paper left out; the paper index behind its setting; the web search off until configured, SearXNG
  and Brave stubbed (the key as a header). On the test database: an entity, a name, a link (another version), a post and
  a question as seeds (the entity's posts, the posts linking its pdf v2); an unknown name proposed and another name
  offered; an empty seed and an unknown entity refused; a run never started by the ingestion tick; the shared unique
  link first, a page 11 posts share left out, one request a link; a near-copy of a pasted text; the maker from the
  platform's address, two hops of declared links, a profile that links back confirmed, never others' posts, the
  unreadable account asked as one `identity` question and its answer through the worker's API; a namesake found by the
  web search asked and kept out; channels through the reader into the scratch area (no source added), Follow (passive,
  provenance `research`), Watch this (a described track, the followed channel active in it, once); the cost guard (page
  requests, identity questions); the paper index's four calls and its cap, references held or not, citing, newer,
  the authors; discussion hits exact only; a re-run's findings not new, the rerun route.
- `test_markx_scout` (29) unchanged and passing; `test_markx_storage`, `test_markx_validate`, `test_markx_api`
  (MX_TABLES) updated for the tables and the kind.
- Worker: `scripts/tests/test_markx_worker.py` `TestIdentity` (fake-claude): a default kind, five pairs a call.
- Frontend: `pages/ResearchPage.test.tsx` (6): the lines in words, every section, follow / not this one / these are /
  watch / run again, the watched track's link, the start page from a typed or passed seed.

## Measure (the two real tests are the gold; to run on the server, not run here)

Research reads with the server's fetcher. After deploy, with Mark X on, the worker run by hand within a stated cap
(`scripts/markx-worker cycle --kinds identity,track`), and the private notes `plan/research/0149-seed-test-notes.md` for
the seeds:

0. **Test 3, a pasted post:** paste the post's text with its two shortened links into `/research`. Expect "The same
   announcement elsewhere" to list the subreddit post INSIGHT holds (`shares the link …` the notebook) first, the
   company blog post among the resolved links (`stats.resolved` on the run, `GET /api/markx/research/<id>`), and no
   other post called the same. Count wrong "same" rows (must be 0).
1. **Test 2, a bare entity name:** type the model's name. Count: the maker found (The maker: the hub org by the
   platform's rule, then its declared accounts), and of the 11 channels found by hand how many are in Channels to
   follow, how many read well, how many are wrong (a wrong identity or a platform's own feed: must be 0). With a web
   search configured (`INSIGHT_WEB_SEARCH`), run it again and count what the search added.
2. **Test 1, the arXiv link:** paste the HTML v3 link. Count: references (held / not held: `papers.held_references`
   of `papers.references`), citing papers, the authors' newer papers (the namesake physicist's paper must not be
   there), discussion hits (each `why` must be an exact id or title).
3. **Requests and cost per run:** `run.spent` (page requests, paper calls, searches, identity questions) and the scout
   run's reads, requests and judgements (`GET /api/markx/tracks/<id>/scout` once watched, or the run's channels), and
   the worker log's cost for the `identity` and `track` calls.

## Open

- **Paper-index calls:** the spec's guard says 2 a paper; references, citing papers and the authors' newer papers are
  three lists, each one OpenAlex call besides the record, so the guard is 4 a paper (`PAPER_CALLS`). Lower it to 2 to
  keep the record and the references only.
- **Question seeds** resolve through search's entity cards (names in the question); 0141's meaning search is not
  built yet.
- **Near-duplicate text** uses Mark X's text shingles, not vectors: the server has no embedder (the worker's runs on the
  owner's device).
- **Two names of one model** are offered as maybe one thing with a link to the other's page; merging stays with the
  owner's entity review queue (another session owns identity.py).
- **X accounts** are read through the configured bridge's profile page; without one an X account is unreadable and its
  identity is asked of Haiku with what the confirming page says.
- "Later citing papers, the maker's new releases and new discussions arrive there": through the followed channels as
  the watched track's active sources; a citing-paper or search-feed watch of its own is not built.
- A post page's Research this is a link in its Mark X panel (the post route's budget), not a button in the post actions.
