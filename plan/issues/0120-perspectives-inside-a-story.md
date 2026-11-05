# 0120 — Perspectives inside a story: what each source adds, and one sheet that keeps only that

Status: **spec, draft** (2026-11-05). Mark X, a Shadow task kind after 0086 part E. It absorbs the stance part of 0097.

## Why (the owner, 2026-11-05)
- "Topicing sources inside a single story to know which to read, which tells different perspective or just mentions the original from the link."
- "In future I want to remove same content, but remain only those added facts and embed them in the same context."
- On the labels: "keep it simple, we might edit labels in future, but for now let's label and then improve."

## What the owner decided (2026-11-05)
- **A story is one happening:** a release, a filing, a paper, an incident.
- **A follow-up is its own story, linked** (0086 E's late-post table).
- **A minor leak hours before the release joins the release;** a leak days earlier, with coverage of its own, is its own story, linked "came true".
- **A review of the same document later is a member** (an S-1 analysis 9 days later). So are the reproductions of a paper.
- **An unconfirmed claim** ("BREAKING: … moves its listing") is a mention, not news.
- **A post about something else, using the story as its premise,** isn't a member. A model rumour built on an IPO is its own story, shown on the IPO story as one "Related" line.
- **The original is found by links and by maker,** and posts are ordered by published time, not received time.

The owner's labels are `testsets/story_def.jsonl` (prototype, private).

## The four labels
| Label | Meaning | Example (generic) |
|---|---|---|
| **original** | the source itself: the maker's post, the paper, the filing | the lab's own launch post |
| **new facts** | anything factual not said before: numbers, tests, corrections, details | "one correction: output is $5, not $2" |
| **opinion** | argues or interprets, with no new facts | "wait for narrow benchmarks before judging" |
| **same** | nothing new: reposts, "it's out", "wow", duplicates | a 9-word "X is out" |

Plus **not this story**, for membership errors. A post that fits two takes the first that applies: original > new facts > opinion > same.

## How it works
1. **Collapse duplicates first** (code): the same account's identical text is one member; the copies are counted, never judged again.
2. **Find the original** (code, no model):
   - the post whose address is the page most members link to;
   - otherwise a post from the maker's own source (the entity's maker, 0090), or its staff;
   - if no post is that page, the page itself is shown as the source.
3. **Order by published time.** A saved page uses the page's own date, not the time it was saved.
4. **Settle "same" by code where it's certain:** text copied from an earlier member (5-word shingle Jaccard ≥ 0.3), or a post that only links an earlier member with under 15 words of its own.
5. **Ask the model** (Haiku, guide `persp-v3`, batches of 10) for the rest. Each member is judged against the original plus what earlier members already said, given as a running list of facts, not the first post alone. It answers with:
   - the label;
   - for new facts, each fact as one line with its exact span (code checks the span is in the member's text).
6. **The story sheet:**
   - the original's summary;
   - "Added by others": the new facts merged, a fact two sources add shown once with both;
   - a correction shown as a correction, not a silent pick;
   - opinions as one line each;
   - "N more say the same", folded.
7. **Related posts** (not members) are one line each: a rumour that uses the story as its premise, a digest that mentions it.

## Storage (on 0086's tables)
- `mx_story_posts.role` gains the four labels: original, new_facts, opinion, same.
- A new `mx_facts` table: story, post, fact text, span, call, and a duplicate-of key.
- The sheet is computed, never stored as prose.

## Measured so far (X1, 2026-11-05, 41 stories, 203 members, 100 labelled by a blind labeller)
- "Worth opening after the first report" was right 87% of the time.
- The seven old roles agreed with the labeller 59 times in 100, the four labels 68 times in 100.
- **Known failures, each with its fix above:**
  - the paper's own page was called "repeat", because it was compared with an earlier retelling and its links weren't used (steps 2 and 3);
  - in a launch story whose first post was a leak, 11 of 20 posts were called "adds" (step 5's running list);
  - one account's three identical posts were judged three times, differently (step 1);
  - long inputs in batches of 20 mixed items up (batches of 10).

## Measure before building
- Run `persp-v3` on X1's 41 stories. Score it against the 100 labels, mapped to the four labels, and against the owner's `story_def` cases.
- Show built right / wrong / missed with the posts and the model's words.
- **Bar:** "worth opening" ≥ 90% right; "new facts" precision ≥ 90%; "original" right on every story where the links decide it.

## Measured (2026-11-05, `persp-v3` on X1's 41 stories; 9 Haiku batches; no new labels)
**Steps 1–5 ran; step 6 (merging facts into the sheet) did not.**

**Against the 100 old labels** (judged against the first post, mapped to the four labels):

| Version | Four labels | Worth opening | "New facts" precision |
|---|---|---|---|
| v3 | 58/98 = 59% (49–68%) | 72/98 = 73% | 19/36 = 53% |
| v1 | 68/100 | 77/100 | 20/22 = 91% |

**The bar is not met.** But the old labels measure the old definition. Of the 40 disagreements:
- 17 are v3 right under this issue's rules:
  - a fact an earlier member already gave;
  - a duplicate whose first copy has the facts;
  - a link post to the source page counted as original;
  - a figure inside an argument;
- 5 wait on the owner's rule for posts that argue with figures;
- 1 is the labeller being inconsistent;
- **17 are real errors: 6 from the code steps, 11 from Haiku.**

These causes were sorted by hand, not blind. A blind relabel under the new definition is needed before the bar can be checked.

**The original by code:**
- 6 stories by links, 4 by maker (whoever members link most: openai.com, x.com/openai and deploymentsafety.openai.com are one owner); 31 had none.
- The paper's saved page is now original in both overlapping stories, ordered by its own date.

**Duplicates:** one account's three identical posts are judged once.

**Spans:** 105 of 108 fact spans occur in their post. All 3 failures are real errors, 2 of them batch mixing at size 10.

**Fixes for the next run:**
1. **The copy rule** needs "few words of its own" and a minimum length, and never applies to the maker's or staff posts. It hid a CEO's launch post, and a post that quoted an announcement and then added its own test.
2. **An original with no text** (a 0-word link post) must fall back to the earliest text post. Otherwise every fact looks new.
3. **A link post whose page is the maker's** counts as the maker's. Staff need a source → organisation map (0090).
4. **Facts must be about the story's subject or event.** A digest's other items, or a rumour built on the story as its premise, go to "not this story" first.
5. **Code enforces the label order** after dropping facts whose span isn't in the post.
6. **Long inputs still mix at 10:** try 5, or one call per story.

## Measured (2026-11-05, second run: `persp-v3.1` and a blind relabel)
**The new labels:**
- One blind labeller relabelled the same 100 members under the owner's rules (`persp_label_v2`). It saw the original found by code and every member in published order, and no model's answers.
- The new labels agree with the old ones on only 62 of 100: the rules changed what "new" means.
- The labeller agrees with the owner on 9 of 10 owner cases. The one disagreement is a post whose facts were in the official launch post, which isn't in the story.

**`persp-v3.1`** (the six fixes; one call per story chunk of ≤ 8 members; 15 Haiku calls). On 98 of the 100; 2 were skipped by a bug that dropped duplicates of labelled posts:

| | v1 | v2 | v3 | **v3.1** | Bar |
|---|---|---|---|---|---|
| Four labels agree | 47% | 45% | 57% | **78%** (68–85%) | — |
| Worth opening | 66% | 63% | 74% | **85%** (76–90%) | 90% |
| "New facts" precision | 68% | 45% | 58% | **76%** (61–86%) | 90% |
| "Original" precision | 8/12 | 2/2 | 8/9 | **11/11** | every one |
| "Not this story" found | 0/7 | 0/7 | 0/7 | **5/7** (1 false) | — |

- **Owner cases:** 8 of 9 right, against 7 of 9 for v3.
- **The originals found by code:** 10 of 10 right, on 14 of 41 stories (links 3, maker 5, maker's page 2, both 4).
- **Spans:** all 117 kept facts were found in their post.
- **All five failures from the first run are fixed:** the CEO's launch post, the mixed-up test, the empty reference, the rumour built on an IPO, the digest.

**What still fails** (22 rows):
1. **Bare link posts to the source** (9). The labeller follows the guide's "a bare link post to one of those is original"; v3.1 says "same" when the source itself is already a member. **This needs the owner's rule:** "same" when the source is in the story, "original" when it isn't? Three of the nine are model-card link posts the code misses, because their link (not their address) is the maker's page.
2. **"New facts" that are estimates, hearsay or already said** (6): "a valuation usually estimated at 1–2T", "unverified reports say…", a promise to test.
3. **One-line takes called opinion** (3).
4. **Missed "not this story"** (2): a maker's staff remark about another product, an unconfirmed "BREAKING" claim. One false: a repeated figure next to an unrelated remark.

**The sheet** (step 6) is built:
- the launch story: 22 fact lines merged into 20, with the price correction shown as a correction;
- the S-1 story: 15 into 14, with the rumour posts as "Related".

Merging misses rewordings ("3x faster", "2–3x faster"), and estimates appear as facts.

**Next:**
- the owner's rule on bare links;
- code reads a link post's main link for the maker;
- facts must be stated, not estimated or reported as hearsay;
- a one-line take is "same";
- fact merging by numbers plus embeddings.

## Measured (2026-11-05, third run: `persp-v3.2`, on held-out stories)
**The owner's decisions applied:**
- a bare link to a source page already in the story is "same" (7 blind labels switched by hand);
- estimates and hearsay are opinion, shown as "Unconfirmed claims";
- a one-line take is "same";
- L5 and L7 hold.

**Held-out data.** 15,250 server posts from 8 July to 5 November, fetched by GET only. Four sets of the server's own stories, none sharing a post with X1:
- held-out-1: 71 stories with 3 or more sources, 303 posts;
- held-out-2: 83 two-source stories, 195 posts;
- held-out-3: 90 two-source stories, 180 posts;
- held-out-4: 74 two-source stories, 148 posts.

**How each set was labelled.** Two blind Opus labellers worked under `persp_label_v3`. No original is marked; they find it themselves. An Opus referee settled their disagreements. The labellers agree on 86–92% of posts, which is the ceiling.

**Discipline.** Every fix came from one set and was then frozen (md5 recorded). The next, still unseen, set was drawn before it ran. Each post is judged by 3 Haiku runs, majority wins.

| Version (what changed) | Dev (X1, tuned on) | Held-out-1 | Held-out-2 | Held-out-3 | Held-out-4 |
|---|---|---|---|---|---|
| v3.1 | 82 / 90 / 75 | — | — | — | — |
| v3.2b (C1–C9) | 83 / 90 / 86 | **63 / 78 / 61** | — | — | — |
| v3.2c (a linked source page counts; "already in the story" is by time) | 79 / 89 / 90 | 67 / 81 / 68 | — | — | — |
| v3.2d (an earliest report is never the original) | — | — | **53 / 77 / 45** | — | — |
| v3.2e (anyone can be the maker) | 76 / 85 / 82 | 67 / 80 / 63 | 65 / 81 / 58 | **64 / 81 / 63** | — |
| v3.2f (Haiku sees each address and who wrote a repost; the maker is a hint, not a label) | 75 / 89 / 80 | 68 / 82 / 64 | 68 / 79 / 59 | 73 / 89 / 70 | **70 / 83 / 62** |

Cells: four labels / worth opening / "new facts" precision, in %. **Bold** = a set's first, clean run.

**Reading.**
- **Dev overstated the result by 15–30 points.** The honest numbers are the bold ones; v3.2f's is held-out-4.
- **Sonnet under the same guide is 6 points above Haiku** (held-out-1: 70% against 64%). The gap is in the rules and the evidence given, not the model.
- **The bar** (worth opening ≥ 90%, new-facts precision ≥ 90%) **is not met.** Worth opening is 79–89%, new-facts precision 59–70%.

**What still fails:**
1. **Original against new facts or same.**
   - Who made the thing, when the maker is a small author: a developer, a channel, co-hosts.
   - Which carrier of a page counts.
   - The labellers disagree most here too. Needs 0090's maker and staff map from real accounts.
2. **New facts against same.**
   - Whether a detail was already on the linked source page, which no member carries, so neither Haiku nor code can check it without the page's text.
3. **Not this story.**
   - A digest or conference recap in which the story is one item.
   - An opinion written from the rumour (the owner's R6) is still sometimes called not this story.

**Code steps measured on the held-out sets:**
- copy 7/7;
- nothing of its own 30/34;
- the forced maker rule 40/51 (now a hint);
- a link post to the maker's page 8/14.

**The sheet.**
- Facts merged by Haiku: "3x faster" and "2–3x faster" are one line, and the price correction shows as a correction.
- The leak goes under "Before the release", claims under "Unconfirmed claims", Related once per post.
