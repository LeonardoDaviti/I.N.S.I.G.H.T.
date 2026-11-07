# 0132 A — Built: voices (Mark IX)

Status: **built** on its branch (2026-11-08), test-first, not merged. Spec: 0132 Part A, with 0078's open questions at
their defaults. Part B (the source analysis page) and Part C (profiles, reads, forwards) are not here.

## What it does
- **Storage, migration 0080:** `voices` (name, kind, `entity_id`, created / confirmed / removed times), `sources.voice_id`
  (one voice per source), `voice_links` (related voices, with evidence), `voice_decisions` (every decision with its
  evidence; "Not the same" keeps a pair from being suggested again). Nothing is ever deleted: removing a voice sets
  `removed_at` and leaves its channels as sources.
- **Suggested voices** (`utils/voice_rules.py`, pure; `db/repo_voices.py` loads; `services/voices_service.py`):
  1. the same address (the same channel twice: "disable one?");
  2. a standing link (a links section or footer to the other's profile in 30% of posts, or 30% of own posts linking a
     source that is no hub, with some link back; a links-section or footer link alone; any link with a shared name);
  3. near-identical own posts (5-word shingles, Jaccard 0.5+, neither a repost) with a shared name;
  4. both official for the same maker (the role rule's step 3).
  - A name alone is "possible", never a suggestion.
  - Platforms are never joined: Reddit, Hacker News, Saved, sites of 10+ authors, aggregators.
  - Related voices: one official and the other 50%+ about its maker; 10+ reposts of one handle. Each says "needs a bio".
  - Computed in a process of its own and kept (`system_settings.voice_suggestions`, again after 24 hours or on "Look
    again"); the owner's decisions since are applied when read, so a decision shows at once.
- **The official rule** is `utils/source_roles.py` (new, shared with 0132 B): `official`, `focus`, `name_tokens`,
  `acronym`, `load_reads` (Mark X's readings and mentions). The voices service takes it through a hook
  (`VoicesService(officials=...)`), so Part B's role rule can replace it.
- **The owner decides**, `routers/voices.py` (one `include_router` line in main.py): Join, Not the same, Related, Make a
  voice by hand, a channel leaves, rename, remove. The voice's name is its main channel's (most posts), editable.
- **Stories count a confirmed voice once** (`story_rules.count_voices` / `StoryPost.counted_voice`): a confirmed voice
  of 2+ channels is an owner `voice:<id>` (`SourceFacts.voice_of`, `owners`). News counts it once too, and names it once
  (the story and News rows' names follow the count, `label.*_voices`). A Reddit poster stays its own voice in a story.
- **The voice page** is the reader at `/read/voice/<id>` (`voice:<id>` is a feed, News, Classics and search scope): one
  stream of every channel, a tab per channel (each the channel's own page, which names its voice), News and Classics as
  on a source page.
- **"Also on <channel>"**: on the Main feed, a track and a voice's page (all and unread), a post that is a near-copy of,
  or links (or is linked by), the voice's other channel's post within 72 hours shows once: the earliest, with a line
  under it. A channel's own page, Later, Kept and History show every post.
- **"Suggested voices"** and "Your voices" are the Sources page's new **voices** tab.
- **Invariant** `voice.one_per_source`: a source in more than one voice, or in a voice that is not kept.

## The deploy regroups nothing
- `rules_stamp()` is the same before and after: `084d186130fb` on a250184 and on this branch (the sample has no
  confirmed voice; `StoryPost` gained no field, only a property).
- A source's facts print is unchanged unless it is in a confirmed voice (`test_the_rules_stamp_reads_no_voice`).
- Confirming, leaving or removing a voice queues **only** the posts of the sources whose counted voice changed (and the
  X posts by or reposting their accounts), then asks for a story run (`in_own_process`, as the start does). Tested on
  the database: the queue holds exactly the voice's channels' posts, the run makes no `rebuild`, the story falls from
  2 voices to 1 and leaves News, a full regroup afterwards changes no row, and removing the voice brings both back.

## Checked on the server copy (once, as allowed)
A scratch copy of `insight_server_1105` (migrated to 0080, dropped after), suggestions only:
- **17 suggested groups, 40 sources: the lab's 16 voices, the same 40 sources, nothing extra.** The one difference: the
  lab's 4-source company voice comes as two groups here (its two sites, each added twice). The lab joined the two by
  "both 60%+ about the same maker and linking each other", which needs Mark X's readings; this copy has none (it is the
  copy before Mark X's tables). With readings on the server, rule 4 and that join apply.
- "Possible": 10 pairs: the lab's name-only misses, and one pair of different people the lab left out (possible only, never suggested).
- Related: the lab's 3 heavy-reposting pairs; the staff <-> company pairs need Mark X's readings, so none here.
- Time: 4.0 s, 196 MB at its peak (in its own process on the server).

## What stays unverified until the server runs it
- The real-data check and the lab re-measurement were not run (the owner's instruction): the story and News rows a
  confirmed voice changes are listed by the owner's own confirmations on the server.
- Rule 4 and the related staff rule on real Mark X readings.
- "Also on" on real announce pairs (the lab counted 102).

## Tests
- Backend: `test_voices` (30: every rule on fixed sources, platforms, name-only, related, the role rule's thresholds,
  counting, the stamp, confirm / not the same / related / leave / rename / remove, one voice per source, "also on", the
  voice scope, the routes) and the stories, News, stamps, incremental, trees, reader, feed, search and checks suites
  (429), all pass.
- Frontend: the voices components (9), feedContext, the reader, Sources and search pages; `npm run build` passes the
  bundle check at +0.96% against the baseline (the budget is +1%: the voice pages and "Also on" are their own chunks).

## For the owner
- Deploy, then Sources → voices: each suggestion with its evidence; Join, Not the same, Related, Make a voice.
- 0078's questions at their defaults: priority and the main digest stay per channel (the voice shows the highest),
  removing a voice keeps its channels, the name is the main channel's and editable.
- The bundle has 0.04% left under its budget.
