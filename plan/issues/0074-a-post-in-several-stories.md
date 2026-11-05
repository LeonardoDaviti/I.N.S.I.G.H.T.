# 0074 — A post in several stories: membership is an edge, not glue

Status: **moved to Mark X Part G** (2026-11-05): Shadow's `mx_story_posts` is this edge model, and Mark IX reads it when a feature switches on (0086 G; the build plan's corrections, 5). Not built in 9.x. Was: spec (draft, 2026-11-01), for v9.14 together with the incremental story job (0071 points there). Owner, 2026-11-01: "if it touches multiple stories, it should touch them. that's the whole complexity of the news, they are nonlinear and multiconnectable." It is the step from tree (0064) to graph (0004, Mark X). Real-data examples stay in `plan/research/` (private); this file uses neutral names.

## Why a post sits in one story today
- **The story job groups with a union-find** (`story_rules._UnionFind`). Every join merges two groups. A post that joins two stories therefore *fuses* them into one.
- **The workaround:** a roundup (3+ anchors, `ROUNDUP_ANCHORS`) joins only the story of its first anchor; its other anchors become `story_mentions` rows.
- **The data matches the workaround:** `story_posts` is keyed by `post_id` (one story per post); `story_mentions (story_id, post_id)` is already many-to-many.
- **What it breaks:**
  - **A bridge fuses two stories.** A post with 1–2 anchors linking two different stories joins both, so the two stories merge: an essay linking a regulator post and a model release puts the regulator post inside the model story (`fable-dma-bridge` in `cases.json`).
  - **A post about two events loses one.** A tweet on "a company files for its IPO, and will release its next model this week" is only in the IPO story.
  - **A roundup is "about" only its first link.** A daily roundup whose first line is yesterday's release is in that release's story and only a mention of the two releases it is really about.

## Measured on the lab copy (2026-11-01, all time)
- 707 posts mention stories they are not in (1,179 mentions); 358 of them since 1 Aug.
- 89 posts are in one story *and* mention others: 61 one other, 17 two, 6 three, and 6 more (up to 8).
- **Not measured yet:** how many stories are fusions through a bridge. Measure it first (A1).

## Decided (draft)
1. **Two kinds of connection.**
   - **Glue (the same thing):** same address, repost, thread, quote of a stored tweet, the same text. Glue merges groups with the union-find, as today. It is certain, and the same item can't be in two places.
   - **Membership (is about):** a link or a citation from a post to a story. It is an edge from the post to the story and **never merges two stories**.
2. **Core stories first, then edges.** The story job builds cores from glue and from posts with a single target (one anchor, or several anchors all inside one core). Then every post with targets in 2+ cores gets one edge per core.
3. **Each edge has a kind:**
   - `about`: the post is about that story. Without Mark X: its first anchor, and any anchor in its title or first paragraph.
   - `mentions`: it names that story but is not about it. Without Mark X: a roundup's other anchors, as today.
   - Mark X step 1 (the same-story check) later decides per edge, and a `no` turns `about` into `mentions`. It no longer moves the post out.
4. **Voices:** a post counts as a voice in **each** story it is `about`. A `mentions` edge counts no voice. Discover's link counts are unchanged; they come from links.
5. **Trees:** a post's parent is chosen per (post, story) edge, not per post.
6. **Reading:**
   - a feed row shows the story with the most voices, plus "and 1 more story";
   - the post page lists every story the post is about, then the ones it mentions;
   - a story lists its `about` posts in the tree and its `mentions` under "Also in roundups", as now.
7. **News:** one post can lift two stories. A story's score counts each voice once.

## Data
- `story_posts`: primary key `(post_id, story_id)`, plus `kind` (`about` | `mentions`), so the `parent_*` columns become per edge.
- `story_mentions` folds into `story_posts` with `kind = 'mentions'` (one table for every edge), or stays as it is if the measurement shows the merge costs more than it gives. Decide at A3.
- Every reader of `story_posts` (reader, News, search, Discover, source anatomy) assumed one row per post. List them and fix each (A4).

## Order
- **A1. Measure first, change nothing:** on the lab, recompute stories with bridges kept apart. Count the stories that un-fuse, the posts gaining a second `about` story, and News rows that appear or vanish. Read 20 un-fused stories by hand (right / wrong / missed).
- **A2. The story job:** glue vs membership, cores then edges.
- **A3. Migration:** `story_posts` many rows per post, with a `kind`.
- **A4. Readers of `story_posts`:** feed row, post page, story page, News, search, Discover, anatomy.
- **A5. Rules-only `about` vs `mentions`** for 2–3-anchor posts (first anchor, title, first paragraph). Mark X replaces this per edge.

## Done when
- `fable-dma-bridge` passes: the regulator post is not in the model story, and the essay is `about` both or `about` one and `mentions` the other.
- Every passing case in `cases.json` still passes.
- On the lab copy: stories, News and Discover are compared row by row with today. Every change is listed and a sample read by hand.
- Tests: a bridge never merges two stories; a post `about` two stories counts one voice in each; a `mentions` edge counts none.

## Where it stands, and why
- **After v9.13, inside v9.14, designed with the incremental story job.** Both rewrite the story job's core. Doing them apart rewrites it twice. 0071 already names v9.14 "incremental story job, stored connections"; these edges *are* the stored connections.
- **Before Mark X step 1 goes into the product, not before its experiments.** The same-story check's labels are per (post, story) pair, so the lab work (label guide, labels, the benchmark) runs now. But what a `no` *does* changes with this issue: from "the post leaves the story" to "the edge becomes `mentions`". Wire the check in only after this.
- **Before Mark X step 2 (stories by meaning).** A meaning join is one more membership edge. Without edges, every meaning join between two existing stories would fuse them, which is the bridge bug at scale.

## Not in this issue
- Edges between stories ("follow-up of", "the release at that event"): Mark X, the graph.
- Ontology tags on a `mentions` edge ("touches the topic, not the same story"; owner, 2026-11-01): Mark X, with entities (0001).
