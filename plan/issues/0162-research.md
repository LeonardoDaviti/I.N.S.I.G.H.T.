# 0162 — Research: start from a link, a name, an entity or a question; INSIGHT finds the maker, its channels, its papers and who discusses it

Status: **spec** (2026-11-10). Stealth (Mark IX's finders + Mark X's identity). Builds on 0138 (originals, addresses,
the rabbit hole), 0143 (the smart archiver), 0144 B (a person's own sources: "By"), 0145 (tracks), 0148 (track scout:
candidates, test reads), 0149 (source check at add: kind, reads, fits). v10.13.5 fixed the class bugs the two real
tests below met first.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; 0138, 0148, 0149 and their built notes;
`ingestion/feed_finder.py`; `markx/entity_addresses.py`, `utils/entity_originals.py`; `plan/research/0149-seed-test-notes.md`
(the two real tests, private: real names).

**The owner (2026-11-10):** on an arXiv paper: "if I add this link to INSIGHT, will it find all the possible linkages,
posts and things that we don't have now, but it will fetch, find sources and so on?" Then: "start not only from a
link, call it research. For example I want INSIGHT to find every related channel we can parse from the creator of
<a model>."

**Constraints:** every source add through the feed finder and page watching; nothing followed without the owner's
tap; fix the class (platform classes, never a site list); keep everything; no real names in committed files; unit
tests (stubbed requests) + the two real tests below as the measure; realdata-check once at release.

## Why (two real tests, 2026-11-10; rows in the private notes)
**Test 1, a link (an HCI paper on arXiv).** INSIGHT holds 0 posts of it, 0 of its 100 references, and follows no paper
source (282 sources: 248 feeds, 30 video channels, 3 subreddits). It holds the neighbourhood: 5 posts of one author's
lab blog, the same lab's earlier work, ~30 posts on the topic. Saving the link reads the whole paper (125k characters,
88 outside links: 64 DOIs, 9 arXiv) but dated it None (fixed in v10.13.5). Outside: a paper index gives 53 references,
1 citing paper and the authors' newer papers; it merged one author with a namesake (identity by name fails there too);
a discussion search by the bare id matched another paper (ids must match exactly); one search API refused anonymous
requests; another rate-limited.
**Test 2, a name (a small model trending on a model hub).** INSIGHT holds 15 posts, 5 voices, two unmerged entities for
it, no maker, no address, though one post it holds links the model's hub page. Following the profiles' own links by
hand found the maker (a person and his company) and 11 channels: model hub org (38 models, 2 demos, 5 datasets), code
repo (35k stars), the person's code-host profile and the company's, a docs site, a package index entry, a dev blog, the
company site (blog, research, publications), a preprint. None declared an X, video or Reddit account. INSIGHT's finder
read 4 of them right, offered the **platform's own blog** for 3 (wrong source; fixed in v10.13.5), and none for 3.

**What this shows.** INSIGHT's world is what its sources post. Research turns one thing the owner points at into the
part of the world around it: what it builds on, who makes it, where they publish, who discusses it, what comes next.

## What it does
### 1. A research run
- Started from the search box or any entity/post page: **Research this**. Its seed is one of: a **link**; an
  **entity** (a model, a person, an org, a paper); a **name** typed (resolved to an entity, or a new one
  proposed); a **question** (0141's meaning search finds its entities first, then each is a seed).
- One run is a page of its own (`/research/<id>`), kept; it shows each step as it lands. Re-run any time (only new
  findings shown as new).

### 2. Step 1: what INSIGHT already has (no request)
- The seed's entity (merging what identity proposes: two names of one model are offered as one, owner taps), every post,
  story, original, address and voice; posts linking any address of it under every version of the address (arXiv abs /
  html / pdf / vN; a repo and its releases).

### 3. Step 2: the maker and the identity graph (requests: platform pages only)
- **Maker from addresses**: a model hub, code host, package index or paper address names its owner (v10.13.5 records the
  owner of `<host>/<owner>/<thing>` as a maker candidate); a paper's authors come from the paper page / paper index.
- **Follow declared links, 2 hops, same identity only**: a profile's own links (a model card's links, a code-host
  profile's website and company, a company site's menu, a paper's author pages). Never a link inside someone else's post.
  Each new address is classified: platform + account kind (person / org / project / paper) by platform rules.
- **Same-identity check**: plain rules first (declared both ways, same handle, the profile names the other);
  Haiku (`identity` task, one call per unclear pair) only for the rest; a name alone never suffices (test 1's namesake).

### 4. Step 3: channels (the feed finder + page watching, per channel)
- Each address through the finder (platform rules: a repo's releases, a code-host user's activity, a package's releases,
  a dev blog, a category feed, a site's pages to watch); a platform with no feed (a model hub org) through its listing as
  a watched page or an adapter (a new kind only when measured worth it).
- **Test read** (0148/0149): up to 20 newest items into the scratch area; health (dates, text, language) and, when the
  run has a track or topic, fit by the track judge. Shown: "<channel> (<platform>): 3 a month · reads well · 14 of 20 fit".

### 5. Step 4: papers and discussion (for papers and the people who write them)
- **Paper index** (a free open index first; one with a key later): references, citing papers, the authors' newer
  papers; matched by DOI/arXiv id exactly. Each paper offered as an original to store (0138 E) and, for references, the
  ones INSIGHT already has are linked.
- **Discussion search**: the search feeds of platforms INSIGHT reads (and, from the server, X through the bridge), the
  query being the exact id or exact title; a hit must contain the id or link the address (no fuzzy matches).

### 6. What the owner gets
- **The research page**: In INSIGHT (posts, stories, entities) · The maker (person / org, with "These are <name>: yes /
  no" for its voices, 0144 B) · Channels to follow (ranked: reads well, cadence, fit; **Follow** / **Not this one**) ·
  Papers (references held / not held, citing, newer) · Discussion found · What could not be read and why.
- **Watch this**: one tap makes a track (0145) seeded by the run: its active sources the followed channels, its words
  and examples from the seed; later citing papers, the maker's new releases and new discussions arrive there.
- Followed channels record their provenance (the run), so their later precision shows (0148).

### 7. Cost guard
- Per run: at most 60 page requests (polite, the server's fetcher, its own budget, logged), 40 test reads, 2 paper-index
  calls a paper, the Haiku `identity` calls (≤ 20, ≈ $0.01) and the test reads' judgements (≤ 800, ≈ $0.15).

## Measure (the two real tests are the gold)
1. From the bare entity name of test 2: the maker found, and of the 11 channels found by hand, how many are found,
   how many read well, how many wrong (a wrong identity or a platform's own feed must be 0).
2. From the link of test 1: references matched (held / not held), citing papers, the authors' newer papers, the
   namesake not merged, discussion hits all exact.
3. Requests and cost per run.

## Done when
- Tests (stubbed requests): each seed kind; Step 1 with address versions; maker from platform addresses; 2-hop declared
  links, never others' posts; the same-identity rules and the `identity` task's schema/validation; channels through the
  finder; the test read in the scratch area (nothing followed); paper index by exact ids; discussion hits exact only;
  "Watch this" makes a track; provenance; the cost guard.
- Worker: `identity` in `DEFAULT_KINDS`, `PER_CALL` `identity=5`; a fake-claude test.
- Migration (research runs, findings, provenance); frontend builds; vitest passes; design docs claim the research page.

## Open (the owner)
1. Which paper index first (a free open one; a keyed one later for references with arXiv ids).
2. Whether "Research this" may run by itself for a new entity that surges (later; costs).
