# 0168 — A person's handles, and reposts credited to their author (built, Stealth v10.15, branch `v1015-handles`)

Part B of v10.15. Evidence: E5 + E7 (2026-11-12, private: `plan/research/exp-2026-11-12/e5e7/`, REPORT.md and
appendix_e7.md). Builds on 0144 B (a person's own sources: "By"), 0133 (roles source / recommended), 0162 (a person's
accounts become known names), 0164 (names by evidence). Names here are invented. **Migration 0112**
(`0112_markx_handles.sql`; renumber at merge if another lands first: nothing depends on the number). Nothing merges by
itself: every new question is the owner's, every new row is a rule's. No worker kind (all rule-based).

## Why (E7, 52 people)
A strict handle rule found 3,786 posts citing them, 528 already on their page: **+3,258** (median 53 a person, 49 of 52
gain). Precision 38/40 uniform, **103/106 = 97.2%** over every sample; the one error class was a round-up's repeated
section header ("The <Group> @h Discord has no new messages" in 93 issues). Bare words: 67%, never used. 31% of the
gain sat in long round-ups past the 1.5k / 6k characters the entities guide reads. "Display Name (@handle)" pairs
agreed 580 of 583 (99.5%). E5: a company's post carried in its CEO's X feed was headlined "<CEO> announces"; an
investor's congratulation read as the founder's.

## A. The handle rule (`markx/handles.py` `scan`, pure; `scan_posts` / `scan_pending` store it)
Over a post's **whole** title and text, its kept links (`post_links`, not boilerplate) and its author fields:

| form | what | role |
|---|---|---|
| `repost` | an X feed's row whose `posts.author` is not the feed's account (Nitter's "RT by @feed"); a Telegram forward whose header names the channel's username | by |
| `quote` | the tweet it quotes (`post_parts.quoted`) | by |
| `embed` | a page's embedded tweet written out: "— Name (@h) May 3, 2026" | by |
| `status` | a status link: x.com / twitter.com / Nitter / xcancel / fx- and vx-twitter; a Bluesky post; a Telegram channel post. It names the cited post's **author**, never its subject | source |
| `said` | "@h said / confirmed / announced / wrote / argued ...", "@h: ...", "according to / per / via / h/t @h", "Tweet from Name (@h" | source |
| `at` | any other @mention | mention |
| `profile` | a profile link (X, GitHub, Hugging Face, Bluesky, Telegram) | mention |
| `reply` | it replies to them (Nitter's "R to @h:") | reply (hidden by default) |

A post's role for a handle is `role_of` its forms: by, then source, then reply, then mention (a reply's own @ is the
reply). **Platforms**: an `@h` is X outside Telegram posts, a Telegram channel inside them; `@name.bsky.social` is
Bluesky; links name their platform. Handles are keyed `(platform, handle)`: the same handle on GitHub and X is two
accounts, joined only by a declared link (0162's research). **Never a handle**: an e-mail, a path's `/@user`, a
Mastodon `@user@host`, an npm scope, a CSS / BibTeX / decorator / GraphQL at-word (a vocabulary of languages), a unit
(`@2x`), a one-letter X handle, a platform's own page (`x.com/search`, `github.com/topics`, `huggingface.co/models`), a
project page (`github.com/<owner>/<repo>`: its maker, 0138), a bare word, and the post's own source's account.

**Boilerplate**, found at read time, nothing hard-coded: a citation whose sentence (folded: case, spaces, digits
outside addresses) 3+ posts of one source repeat, or a mention whose nearest words (the word before, the handle, the
word after, punctuation skipped) 5+ posts of one source repeat (a round-up's section header "<Group> @h Discord <the
next item>" repeats there though its sentence never does; a list "@a , @h , and @b" keeps its neighbours). Digits are
kept inside addresses, so a quoted tweet's own link line is never furniture.

**When**: the decision run's entities stage (`entity_stage.handles`, after the renames, in a savepoint): up to 5,000
pending posts a run in batches of 500, newest first, within the stage's budget (one batch always, so a long full pass
never starves it). Pending = no scan, an older rule (`STAMP`), or new text (`content_hash`). A post read again gets a
new row set under a new digest; the old rows stay, unread. Backfill: `python -m insight_core.markx.handles scan`
(every pending post, a transaction a batch of 500).

## B. The person page (`entity_views.entity_page`)
Known handles = the owner's yes (`mx_entity_handles`, newest answer counts) and the accounts of the entity's own
sources (0144 B1's "By": a followed X / Telegram / GitHub / Bluesky / Hugging Face account is theirs, no question).
The posts citing them (`handles.posts_citing`, the entity's own sources left out, boilerplate left out) join the page's
lines with their role: `by` (also the story's original, 0144 B3), `source`, `mention`; named "@h". Replies are counted
and hidden (`handles.replies`); `GET /api/markx/entities/{id}?replies=true` shows them. The page has a **Handles**
line: each handle and platform, an old one with the months its pairs span, "its own source", "N posts cite them",
"show N replies to them". `POST /api/markx/entities/{id}/handles {platform, handle, answer}`: the owner says or denies
one directly.

## C. Handles learned from pairs (`handles.learn`, after the scan each run, at most 50 questions a run)
Each "Display Name (@handle)" in a text is stored (`mx_handle_pairs`: the name cut at the sentence's punctuation, its
lead words dropped: "Tweet from", "Quoting"; a long run keeps its trailing capitalised words). A handle whose pairs
agree (the top name in **2+ posts and 90%+** of its pairs) is asked once (`mx_entity_queue` kind **`handle`**, a = the
entity, the handle in the evidence: display name, pairs, total, first and last, examples) for the **one** person or
org of that name (names and aliases by identity's squashed key). Two entities of the name: never asked (namesakes).
Already the owner's for someone: never asked. A **second handle** paired with the same name while the entity has one
on that platform is asked as `second_handle` with `alias_of` and its time range (a renamed account). **Never a
handle by name alone**: only pairs, the person's own followed accounts, or the owner. Answers (`entity_answers`):
`same` ("yes, theirs") records it with the display name and time range; any other answer records a no, never asked
again. The queue card: "Is @h <name>'s X handle?", "N posts write “Name (@h)” · 2023-01 to 2024-03 · their other
handle @x", answers "yes, theirs" / "no".

## D. Entity names that came from handles
An entity whose name is a handle with agreeing pairs (named "ikestrel", typed an org): when an entity of the display
name exists, an **alias question** (reason `handle_name`, evidence the pairs); the owner's `same` merges them as any
owner merge (0164 A's guard) and records the handle as the display-name entity's. When none exists, a `handle`
question (`named_by_handle`): its yes keeps the handle (the entity's name stays one of its names) and shows the display
name at once; `entity_repair.shown` keeps it (a cluster shown under one of its confirmed handles is shown by the name
its pairs gave, `handles.learned_names`; never over an owner's rename). The type is not changed by a handle.

## E. Reposts credited to their author (`markx/tasks.py`)
`tasks.Post.by`: the original author of a post its feed carried but did not write (`original_author`: on X an author
that is not the feed's own account; a Telegram forward's channel name). The reading inputs (read, entities, and the
track judge's post block) say `Author: @acme (a post by @acme shared by <feed>; not <feed>'s own words)`; the card,
headline and briefing inputs show such a member as `[a post by @acme shared by <feed>, x, ...]` and the briefing's
sources by author; `tasks.voices` counts a repost as its author's voice (two feeds carrying one account's post: one
voice). The sameness questions (check, join, pair, merge, connect) are unchanged: they ask whether two posts tell one
story, not who said it, so they are not asked again. A post whose input changed (a repost) gets a new reading, card
or headline task when next planned; its old answer stays until then.

## Checked offline (the local copy to 5 Nov, the pure rule without the database; not a labelled measure)
- 49,384 posts scanned in ~8 minutes (one process, pure Python; the server's runs take 5,000 a run).
- Forms: at 13,449 · repost 3,818 · status 3,274 · said 1,228 · profile 666 · reply 415 · embed 5 (author fields of
  `post_parts.quoted` were not in the copy, so no `quote`).
- Boilerplate: 55 repeated lines, 1,339 refs left out; E7's round-up header held in 91 issues (that person's posts by
  the rule 35 → 5). A first version keyed mentions by any neighbouring token and dropped real citations in lists ("@a ,
  @h , @b") and quoted tweets' own link lines (digits folded inside addresses): fixed (neighbouring *words*, digits kept
  in addresses), and rechecked: only the header and one tweet quoted three times in one feed remain (that post keeps
  its `quote` row, so it stays `by`).
- I read 80 random refs: wrong were "x.com" inside another host ("thejerx.com/blog"), GraphQL directives ("@auth ,
  @searchable"), a one-letter truncation ("@a [...]"); each fixed with a test. The labelled precision read is after
  deploy (below).
- Pairs: 2,278 over 1,347 handles; 94 handles have more than one name, almost all a word glued in front ("Video <Name>",
  "FixupX <Name>", a city): a name's support counts every pair ending with its words, so they agree.

## Tests
- `tests/test_markx_handles.py` (pure): each form and role; a status link names the author not the subject; repost,
  quote and reply from the author fields, the feed's own account never; never-a-handle cases (e-mail, CSS, BibTeX,
  decorators, npm, Mastodon, a path's @, units, a bare word, a host ending in "x.com", GraphQL directives, one letter);
  Telegram and platforms apart; kept links; the full text past 30k characters; `role_of`; boilerplate keys; pairs
  (lead words, trailing names, one lowercase word, Telegram, no name); a source's own account.
- On the test database: a scan stored once and read again on new text (old rows kept); the entities stage scans;
  the page by role (source, status, repost = by, mention, a reply hidden and shown on asking, the newest answer
  counts); the same handle on GitHub is not the X one; the person's own source is a known handle and its posts stay
  `by`; a header 5 issues repeat is boilerplate, once elsewhere a mention; `add_handle` refuses non-handles; the API's
  404s; one pair asks nothing, two ask once, the owner's yes shows the handle with its display name, never asked again;
  a name alone asks nothing; a no; disagreeing pairs ask nothing; a second handle with `alias_of` and its range; an
  entity named by its handle shown by the pairs' name after the yes (and the run keeps it); with the display name's
  entity an alias question, merged only on the owner's `same`; a repost's reading / headline / card / briefing inputs
  and its voice; `original_author`.
- `test_markx_api.MX_TABLES`, `test_markx_storage` (the four tables), `test_entity_originals.DELETE_ORDER` updated.
- Frontend: `components/markx/handles.test.tsx` (the Handles line, an old handle's months, show replies; the handle
  question's card and answers).

## Measure after deploy (the owner's server; realdata-check at release, not here)
1. Backfill: `docker compose exec backend python -m insight_core.markx.handles scan` (or let the runs do it, 5,000 a
   run). Then `learn` runs each decision run (or `python -m insight_core.markx.handles learn`).
2. **Precision read of 40**: confirm handles for the 52 E7 people (their own followed X accounts are known already;
   others through the queue or `POST /api/markx/entities/{id}/handles`). Draw 40 uniformly from the posts that joined
   their pages by the rule (`mx_handle_refs` current rows, own sources and boilerplate out, replies out), and label
   each: right (the post cites the person: they said / their post / a real mention) or wrong (the class: boilerplate,
   another person's handle, code). Bar: 95% (E7: 97.2%). Report the wrong rows exactly (post → form → label).
3. **Gain per person**: for each of the 52, page posts before (E, appendix_e7) and after, the gain by role
   (by / source / mention) and the hidden replies; expect ~+3,258 over the 52 (median ~53), more with the 2024-25
   round-ups the local copy lacked.
4. **Pairs**: the open `handle` questions (count; read 20: is the display name the person and the handle theirs?),
   the agreement (top-name share of all pairs; E7 99.5% on its pairs) and the `second_handle` ones (old accounts).
5. **Reposts**: the stories whose members include a repost: re-asked headlines; read 20: none says "<feed owner>
   announces" for another account's post (E5's two cases first).
6. Time: the entities stage's `handles` counts and seconds per run in `mx_runs.counts`; the backfill's posts/second.

## Left off
- **decide.py's voices** (the story rules' min-voices, `decide.voices`) still count by source: decide.py belongs to the
  incremental-cache slice. One line there (`decide.Post(pid, p.voice, ...)` in place of `p.source_id`, with tests)
  makes stories count a repost as its author's voice too; until then only the inputs and `tasks.voices` do.
- Telegram forwards are credited by name (the forward header's `name`); a forward's channel username is read when the
  header carries one (`forwarded_from.username`), which the current ingestion does not store.
- No type change from a handle (an org named by a person's handle stays typed org unless merged into the person).
- No handle from a Mastodon account (`@user@host`) or a bare Bluesky domain outside `.bsky.social`.
- Mark IX's story voices and headlines (`stories_service`, `repo_reader.story_voices`) are unchanged.
- Cross-platform handles only through a declared link: not joined automatically here (0162's research does it on a
  run; nothing reads its result into `mx_entity_handles` yet).
