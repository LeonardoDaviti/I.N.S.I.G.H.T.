# 0133 — ent-v4: documents, filings and cited sources as entities; entities read 6,000 characters; a citation rule

Status: **spec** (2026-11-08). The build can start now. **The guide (`ent-v4.md`) arrives from the lab when `out/entv41_v1/` passes;** the deploy waits for it (see "The guide and the gate"). Stealth. Builds on:
- ent-v3 (the `entities` kind);
- 0119 A (identity, the entity page);
- 0131 (edges);
- `candidates.document_key` and 0109's document shapes;
- 0125 (`post_refs`).

**The owner (2026-11-06)**, on a post that relays a forecaster's numbers about a company's filing: the filing and the forecaster weren't entities, so nothing connects them across posts.

**Constraints:**
- keep everything: old ent-v3 answers stay stored; the new guide adds tasks, never rewrites old rows;
- no real names in committed files;
- fix the class, never a site;
- nothing merges unless `scripts/realdata-check.sh` passes;
- the worker runs by hand.

## Why
- **ent-v3 has no document type and reads only the first 1,500 characters.** A filing, report, paper or forecast cited as evidence is typed `other`, or isn't extracted. An organisation whose claim the post relays is missed or called a venue.
- **Measured** (lab `out/entv4_v1/`, private; 80 unseen posts that relay or cite, and 60 ordinary posts):
  - **ent-v3 finds 36%** of the gold documents and cited organisations;
  - **past character 1,500, it finds 11–16%.**
- **ent-v4** (a document type, a source role, 6,000 characters) was measured on the same posts:
  - recall **61%** against a 70% bar;
  - new-entity precision 90.6% (lower bound 85.02%, passing), but one of its 3 runs failed;
  - precision on ordinary posts +1.6 pts.
- **The misses that remain:**
  - **reference lists:** 10 posts held 95 of the 234 gold items ("Author et al. (YYYY)", lists of filings). A rule should find these, not Haiku;
  - **five wrong-row classes,** which the guide fixes (ent-v4.1, being measured).
- **The owner (2026-11-08):** books, videos and courses a post recommends **are documents**, with a role of their own (`recommended`), apart from cited evidence.

## What it does
### 1. Entities read 6,000 characters
- A new `ENTITY_TEXT_CHARS = 6000` in `markx/tasks.py`, used by `entities_input` only.
- `TEXT_CHARS` (1,500) stays for `read` and `embed`.
- Measured cost: +46% per entities task ($0.00136 against $0.00093 a post).

### 2. The schema
- `ENTITY_TYPES`: `paper` becomes **`document`** (a paper, filing, report, forecast, law text, book, video, course).
  - Stored ent-v3 answers with `paper` read as `document` everywhere they're read: identity, candidates' `SPECIFIC_TYPES`, the entity page.
  - No stored row is rewritten.
- `ENTITY_ROLES` adds:
  - **`source`:** the post relays or cites its claim, data or forecast as evidence (an organisation, a person or a document);
  - **`recommended`:** a work the post recommends or reads, not cited as evidence (a document only).
- **A document may carry `by`:** its publisher or author, an organisation or person named in the post. Identity stores it as a `published` link between the two entities (0131's entity edges).

### 3. The citation rule (no model)
Run over the full stored text and `post_refs` before the entities task is stored. Each hit is a mention: type `document`, role `source`, `rule='citation'`.
- **In-text citations:** "Author et al. (YYYY)", "Author (YYYY)", "Author & Author (YYYY)", "Author and Author, YYYY", in English and Russian. **The exact patterns come with the frozen lab result.**
- **Identifiers:** arXiv ids and links, DOIs.
- **Links to documents:** every `post_refs` link whose `candidates.document_key` is a document (a paper by its id; a record or filing by 0109's shapes).
- **Merged with Haiku's mentions:** a rule hit and a Haiku document naming the same thing (the same DOI or arXiv id, or the same identity key) are one entity. The rule's span is kept, and Haiku's role wins when it isn't `source`.

### 4. Re-extraction
- **A new guide is a new task** (tasks are unique per kind, guide and input). So the planner adds `entities`/`ent-v4` tasks newest first, within the reading window, like any guide change. The worker answers them when run by hand.
- **Cost at the measured rate:**
  - last 30 days (about 5,600 posts): about $8;
  - 120 days (about 15k): about $20;
  - all posts (about 58k): about $80.

  The owner chooses the window on `/markx` (the reading-window setting).
- **The current mention set:**
  - a post's entities come from its newest valid entities answer;
  - ent-v3's rows stay stored, and the post page shows which guide it came from;
  - identity (0119 A) runs incrementally on the new mentions.
- **The decision run's entity stage** (budget 63 s of 120 s on v10.5) must stay within its limit. Measure it on the server copy.

### 5. Where it shows
- **The entity page and its list:** documents get pages like any entity, showing who published them, the posts citing them (`source`) and the posts recommending them (`recommended`).
- **The Mark X post panel:** the post's documents and cited sources, under their roles.
- **Surges** (0119 A2) count only subject and actor roles. `source` and `recommended` never make a surge.

## The guide and the gate
- **The build doesn't wait for the guide.** Everything above is code: the schema, the cut, the rule, re-extraction, the pages.
  - The build ships `guides/ent-v4.md` as a placeholder: ent-v3's text with the new types and roles described.
  - Its tests run on fixed answers, not on the guide's wording.
- **When the lab passes** (`plan/research/lab/markx/proto/out/entv41_v1/REPORT.md`), its frozen guide replaces the placeholder byte for byte. The md5 is checked in the merge commit, and the rule's patterns are taken from the same report.
- **The lab's bars**, on fresh held-out posts:
  - new-entity precision lower bound ≥ 85% **on all three runs**;
  - recall of documents and cited organisations ≥ 70%;
  - ordinary posts no worse than ent-v3 by more than 2 pts;
  - `recommended` precision reported separately.
- **If ent-v4.1 fails,** the fallback is the same build with **ent-v3's guide at 6,000 characters**. It's measured in the same run as its own arm with the same bars; it went from 36% to 50% recall at 96% precision on the old set. Plus the citation rule. The new roles then come only from the rule.
- **If both fail,** nothing switches. The code ships with the guide switch on ent-v3 and the 1,500-character cut, so nothing changes until the owner decides.

## Measured (2026-11-08): ent-v4.1, and the fallback, on fresh held-out posts
Lab `out/entv41_v1/REPORT.md` (private). Fresh sets: 90 posts that relay or cite, and 70 ordinary posts; overlap 0 with every earlier set. PREREG md5 `4793e123…`. Gold: two blind Opus labellers and a referee.

| Bar | ent-v4.1 + citation rule (6,000) | ent-v3 at 6,000 (the fallback) | ent-v3 at 1,500 (today) |
|---|---|---|---|
| New-entity precision, lower bound ≥ 85% on each run | **91.1 / 93.3 / 94.4%** (lower bounds 86.6 / 88.9 / 90.2): **passes** | (all entities) 97.8 / 97.5 / 96.6%: passes | — |
| Recall of documents and cited organisations ≥ 70% | **58.0%**: **fails** | 38.3%: fails | 30.1% |
| Ordinary posts ≥ today − 2 pts | **98.2%** against 98.6%: **passes** | 96.1%: **fails** (−2.5) | 98.6% |
| `recommended` precision (reported) | 34/39 = 87.2% (73.3–94.4) | — | — |
| **The rule's text forms alone** (Author et al. YYYY, Author (YYYY), arXiv, DOI) | 42/42 on test, all right on dev | — | — |

**Verdict:** neither guide passes, so the switch stays on ent-v3 at 1,500, as built.
- **ent-v4.1 is better than today on every measure:**
  - recall +28 pts;
  - cited organisations 68–71% against 49–53%;
  - precision passes on all three runs, which ent-v4 didn't;
  - ordinary posts within 0.4 pts.

  It only finds too few. Its errors are misses, not wrong entities.
- **Cost:** about +94% per entities task.
- **The 6,000 fallback is ruled out:** it adds 8 pts of recall and loses ordinary precision.
- **Why recall stays short:**
  1. Haiku stops at about 7–8 entities in dense posts.
  2. Studies cited only by a link whose shape INSIGHT doesn't know: PMC, PubMed, ScienceDirect, RFC numbers.

**The owner's options:**
1. **Turn on the citation rule alone** (its text forms, 42/42). No Haiku cost, no guide change.
2. **Ship ent-v4.1 in Shadow anyway,** with label buttons, stating "precise 91–94%, finds 58%". It adds only right entities, compared with today.
3. **ent-v4.2 first:**
   - a second, narrow Haiku question ("every document and cited organisation, nothing else"), only on posts with citation cues (about 15%);
   - wider link shapes (PMC, PubMed, ScienceDirect, RFC/ECMA), which is the 0106/0109 shape list;
   - three guide fixes:
     - `source` only for organisations, people and documents;
     - a model, benchmark or method is never a document;
     - the span names the document.

   Then a re-measure.

**The frozen guide** (if the owner picks 2): `plan/research/lab/markx/proto/guides/ent41_extract.md`, md5 `4c2aea76eaddc199dd60f5ad640af37b`, with the code step `entv41_rule.finish` (drop a document that is the post's own title; add rule documents Haiku lacks). The rule's exact patterns are in the report.

## Measured (2026-11-08): ent-v4.2, on fresh held-out posts
Lab `out/entv42_v1/REPORT.md` (private). 90 relaying and 70 ordinary posts, none used before (the population was extended to Apr–Jul by the same rule). PREREG md5 `de5d85e3…`.

| Bar | ent-v4.2 (+ second question on cue posts, wider link shapes) | ent-v4.1 (frozen) on the same posts | ent-v3 today |
|---|---|---|---|
| New-entity precision, lower bound ≥ 85% each run | 84.0 / 84.9 / 82.4% (lower bounds 77–80): **fails** | 81–84%: **fails** (it was 91–94% on its own test) | — |
| Recall ≥ 70% | **75.6%: passes** | 53.8% | 25–29% |
| Ordinary posts | **98.7%: passes** | 97.0% | 95.7% |

- **The precision failure is the citation rule's, not Haiku's:**
  - Haiku's own new entities are 89–93% right;
  - the second question's additions are 88% right (it adds about 6 pts of recall);
  - the rule's documents are only 70–73% right.
- **Its errors are the post's own papers and self-citations** ("Paper: arxiv.org/abs/…", "(Author et al., 2025)" by the same authors), and links on a dataset or concept name.
- **The rule's text forms were 35/53 = 66% here,** so ent-v4.1's 42/42 doesn't hold. **Don't turn the rule on alone.**
- **Post hoc** (not a verdict): ent-v4.2 without the rule's links is 89–93% precise (lower bounds 83–87) at 60–63% recall. No variant passes both bars.

**Next (ent-v4.3):**
- an own-paper guard for the rule ("Paper:", our / this work anchors, self-citations, the post's own title);
- no one- or two-word name anchors;
- drop OpenReview, and anchor naming for PMC and PubMed;
- dev that includes posts about their own paper;
- then a new pre-registration and fresh posts.

## Handoff: ent-v4.2 in Shadow, measured on the server by the owner's labels (owner, 2026-11-08)
The owner wants ent-v4.2 on the server now, tested there, while ent-v4.3 fixes the rule in the lab.

**What ships: ent-v4.2's two Haiku questions, with the citation rule off** (the lab's post-hoc "main + cite, no rule" arm).
- 89–93% precise on new entities (lower bounds 83–87) and 60–63% recall, against today's 25–29%.
- Ordinary posts 98.7%.
- The rule stays off: it was 66–73% right. It comes back with ent-v4.3's own-paper guard.
- This is a post-hoc number, not a pre-registered pass, so **the server's labels are the measurement.**

**Build** (a new switch arm `ent-v4.2`, beside `ent-v3`, `ent-v4` and `ent-v3-6k`; default unchanged):
1. **The main question:** `guides/ent-v4.2.md` ← `plan/research/lab/markx/proto/guides/ent42_extract.md`, byte for byte (md5 `81c469a1a9a0dce9128e2672e3c40089`), at 6,000 characters, with `ENTITIES_V4_SCHEMA`.
2. **The second question:** a new task kind `cite`, guide `cite-v1` ← `guides/ent42_cite.md` (md5 `4e46eca8e320f831d88dde2130bc681a`), at 6,000 characters plus the post's first 12 links.
   - **Its schema:** entities of type document / org / person; documents with role source / recommended (subject is dropped in the merge); org and person with role source only; at most 30.
   - **Planned only for posts the cue rule picks** (`entv42_run.cue`, about 15% of posts):
     - text ≥ 800 characters with ≥ 2 distinct citation cues (`entv4_sets.CUES`), or
     - ≥ 1 in-text citation (author-year, arXiv id, DOI) in the first 6,000 characters, or
     - ≥ 1 of the first 12 links with a document shape.
3. **The merge** (`entv42_rule.finish` with the rule off), ported with its tests:
   - drop documents that are the post's own title (main and cite);
   - `cite_fix`: an author-year citation typed person or org becomes a document;
   - `merge_cite`:
     - skip a cite `subject` document;
     - skip a document whose span describes rather than names (`name_span`);
     - skip a cite document the main answer typed as a model, software, dataset, event, law, other or place;
     - add the rest that the main answer lacks, marked `q2`.
4. **The citation rule stays off** for this arm (`citations.py` isn't called).
5. **The page:**
   - the post panel marks the second question's entities;
   - every new entity (document, `source`, `recommended`) gets right / wrong buttons;
   - /markx shows the running precision from the owner's labels;
   - the page states "lab: 89–93% precise, finds about 62%; post hoc".
6. **The owner turns it on** (Worker tab) and runs the worker for a window. Cost about $0.0013 a post, plus $0.0009 on cue posts: about $9 for 30 days, $25 for 120 days.

**Leaving Shadow:**
- after 100+ labelled new entities with precision lower bound ≥ 85%;
- or when ent-v4.3 passes its fresh pre-registered test. Then ent-v4.3 replaces it the same way.

## Handoff: putting a measured guide on the server (owner, 2026-11-08)
v10.7 is deployed with the switch off. The owner wants ent-v4 on the server in Shadow.
- **ent-v4.2** (`out/entv42_v1/`, running) is the one to ship if it passes.
- **ent-v4.1** (frozen, measured above) is what ships if v4.2 fails or the owner doesn't want to wait.

**For a guide that is only a guide change (ent-v4.1):**
1. **Replace the placeholder.** `backend/insight_core/markx/guides/ent-v4.md` ← `plan/research/lab/markx/proto/guides/ent41_extract.md`, byte for byte. Put its md5 (`4c2aea76eaddc199dd60f5ad640af37b`) in the commit message. The first line is no longer the placeholder marker, so `schemas.is_placeholder` lets the switch accept it.
2. **Check the guide's answer shape** against `ENTITIES_V4_SCHEMA` (types, roles `source` / `recommended`, `by`). The lab validated against its own copy; any difference is a schema fix, never a guide edit.
3. **Make `markx/citations.py` the lab's rule.** The measured numbers are for `entv41_rule.py`. Port, with its tests:
   - **the own-title guard:** drop a document, Haiku's or the rule's, whose name or span carries ≥ 80% of the post title's words;
   - **parenthesis lists:** each `;`-separated part of "(see A 2020; B et al. 2021)" read alone;
   - **link names:** a document link (`document_key`) is named only from an author-year anchor, or a title-like anchor (≥ 3 words, no address or code, a capital first, and either > 50% of its 4+-letter words capitalised or ≥ 6 words). Skip anchors with our / my / мой / наш, and skip id-only names;
   - **the merge:** a rule document is already present on the same id, the same author and year, a span containment, or ≥ 60% of the title's words;
   - at most 25 rule documents a post.
4. **Tests, the real-data check, push, `./update`.** Nothing changes on deploy: the switch is still off.
5. **The owner turns it on** (Worker tab → entities guide → ent-v4) and runs the worker by hand for the chosen window:

| Window | Cost at $0.00126 a post |
|---|---|
| 30 days | ~$7 |
| 120 days | ~$19 |
| everything | ~$73 |

The page states the measured numbers ("precise 91–94%, finds 58%" for ent-v4.1).

**If ent-v4.2 passes, it is not only a guide swap.** Besides steps 1–5 with its own guide, md5 and patterns:
- **its second question:**
  - a narrow `cite` call, made only on posts its cue rule picks (about 15%);
  - its own guide and schema;
  - merged into the post's mentions by the report's dedupe;
- **its wider link shapes:** the per-shape patterns its report keeps (PMC, PubMed, ScienceDirect, RFC/ECMA/ISO, preprint servers), added to `document_key`'s shapes, one test per shape.

The report gives the cue rule, both guides' md5s and the patterns. That build is about half a day more than ent-v4.1's.

## Not in this issue
- Fetching linked documents so they become stored posts (0113, 0114, 0123).
- Numbers inside documents (0095).
- A document's own page reader: what the filing says.

## Done when
- **Tests:**
  - the cut is used by entities only;
  - `paper` is read as `document` in every reader;
  - the new roles validate;
  - `by` becomes a `published` link;
  - each citation pattern on fixed texts (English and Russian), and the rule–Haiku merge by DOI, arXiv id and identity key;
  - a guide change plans new tasks without rewriting old rows;
  - the newest valid answer is current;
  - surges ignore `source` and `recommended`.
- **On the server copy:**
  - the entity stage's time with the new mentions (within its share of 120 s);
  - the rule's hits per 1,000 posts;
  - the re-extraction's planned task count per window.
- **The real-data check passes:** Mark IX's tables are unchanged, and every current mention names its guide or `rule='citation'`.
- **The lab's frozen guide is in place,** with its md5 in the merge commit, before the deploy.
- **The owner's review:** 20 relaying posts and 10 ordinary posts, right / wrong / missed.

## Bug (owner, 2026-11-17, v10.24 on the server): a document's Original is a paper it cites
- "Anthropic report on the Z.ai model's cyberattack risk" (document · provisional · 3 sources · 7 posts; published by
  Anthropic; also written "Anthropic GLM-5.3 report", "Anthropic blog post on GLM-5.3 and the spread of advanced cyber
  capabilities", "Anthropic report on GLM-5.3 abliteration"…). Its **Original** is `https://arxiv.org/abs/2602.06911`
  (paper, found by its identifier, not collected): "TamperBench: Systematically Stress-Testing LLM Safety Under
  Fine-Tuning and Tampering", a paper the posts cite, not the report. The owner: "how is this paper original for the
  blog post? do we have the blog post itself?"
- Same class: "Anthropic S-1" (the filing) has Original `arxiv.org/abs/2401.05566` ("Sleeper Agents"), rule
  `identifier`.
- The class: the `identifier` rule takes an identifier found in a post naming the document as the document's own
  address, without checking the identifier's page is by the document's publisher (Anthropic ≠ the paper's authors) or
  that its title matches the document's names. Fix: an original must be published by the document's `published_by`
  (domain or authors) or match its title; otherwise it is a citation (`citing`), never the Original. Then: find
  whether the report's own page (anthropic.com/research/…) is stored, and add it as the Original if so.
- Backlog: 0225 #26.
