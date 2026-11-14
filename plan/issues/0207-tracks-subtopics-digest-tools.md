# 0207 — Tracks: evolving sub-topics, a digest per sub-topic, new since you looked, tools in use; practitioner tools that never reached a track

Status: **built** (branch `v1018-tracks` from `v1018`), not merged, not pushed, not deployed. Migration **0140**.
Real rows (titles, sources, every label) are private: `plan/research/tracks-1018/` (gitignored). Names below are
invented.

## The owner's design (2026-11-13)

A track is a topic the reader follows; its definition is "tools and methods practitioners use or build". Build:
evolving sub-topics found from the data with stable ids; a digest per sub-topic with citations, rebuilt only when its
members change; "new since you looked" per track and per sub-topic; a "Tools in use" panel from the entities (product
and tool kinds), counted by voices and recency, linked to entity pages; and fix the class behind: in an agent-workflows
track the reader was suggested generic news, while practitioner tools discussed in followed sources (a terminal app, a
multiplexer for agents) never appeared.

0154 (seen state) was never written: 0094 ("since you last looked", future) was the only spec; the seen state is
built here (section 3).

## Why the practitioner tools never appeared (read on the server with GETs only)

The agent-workflows track on the server: 259 posts in the track (its 4 active sources), 3,014 in Discover, 34,374
judged out, 0 owner labels. The 16 posts that named the two tools the owner named:

| where they stood | posts | why |
|---|---|---|
| judged out | 7 | "no copyable workflow or setup detail", "a product feature announcement", "a tmux replacement rather than an agent workflow", "a product recommendation rather than a detailed workflow" |
| in Discover | 4 | judged in (0.7-0.9), below the 100 Discover shows (all 0.9-0.95, many from 2025) |
| in the track | 2 | an active source |
| never asked | 3 | `below_bar`: no finder put them up (the probe bar 0.48) |

Three causes, one class: **a track's practitioner tools reach neither the judge nor the reader**.
1. **The definition and the judge (fit).** The description asked for workflows "with enough detail to copy"; the guide
   (track-v1) told Haiku that "news about a company in the field is out", and it read a tool's release, feature or demo
   as product news. With the owner's new definition Haiku still judged a tool post out as "a product, not a method"
   (an agent platform's release: "too thin on methods"; an MCP feature: "a product feature, not a practitioner tool").
2. **The finders.** The domain and word finders learn only from the owner's ✓; with no label they learned nothing, and
   a tool post whose wording is far from the example posts was never asked. Nothing knew which tools the track's own
   practitioners discuss.
3. **The fit of a source.** "Make it active" suggestions were ranked by how many in-posts a source had in 30 days:
   general firehoses won (a subreddit 168, an all-posts blog feed 99, an aggregator 61, a forum 11, a lab's news feed
   3), each matching by volume among thousands of posts; the practitioners whose posts discuss the tools had few.

## What was built (each in the module that owns the decision)

1. **Sub-topics** — `markx/track_subtopics.py` (new; owns them; tracks.py's 0145 proposal code moved here, no second
   path). In the jobs process ("tracks" job, before the pages are kept; never the API):
   - proposed from the posts' BGE-M3 vectors, all distances in Postgres (pgvector): warm-started Lloyd's rounds from
     the current centroids (ids stay), new sub-topics seeded where posts are served worst while under the target
     (about √(posts/8), 3-12), past it only from posts no centroid serves or Haiku found no home for; a dissolved or
     emptied one is closed, a provisional one merged into a near twin; quiet after 30 days with no new post (shown
     last, folded); `new` in its first week;
   - **named by the worker** (`subtopics`, guide subtopics-v2: the provisional ones and those whose members drifted
     ≥ 50% since named, shown by their most typical members);
   - **placed by the worker** (`subtopic_place`, guide subtopic-place-v1, 20 posts a question): the vectors alone put
     59% of posts in the right sub-topic; Haiku places each post in one named sub-topic or none (Other); its
     placements and the owner's pins are kept by every later clustering;
   - the owner's rename (in place, same id), merge (pins), split (by the judge's words), add, lock;
   - `tracks.plan_member_vectors` (the embed planner's seam): the posts in a track are embedded whatever the reading
     window (on the server most active-source posts had none).
2. **Digest per sub-topic** — kind `digest` (guide digest-v1): 2-4 one-sentence points over the newest 8 members, each
   citing posts `[n]` (checked: only the question's posts). A question is asked again only when those members changed
   (the same members are the same task), at most every 12 h a sub-topic; the page marks a digest `stale` meanwhile.
3. **New since you looked** — `mx_track_seen` (one look per track and per sub-topic), `GET/POST
   /api/markx/tracks/{id}/seen`. The kept page carries each section's `joined` times and each item's `joined_at`; the
   reader counts what is new since the look before this visit (the kept page never depends on a look: no rebuild per
   open). Opening the topic records a look; **mark seen** records a sub-topic's.
4. **Tools in use** — `markx/track_tools.py` (new; one decision, two readers): entities of the track's judged-in posts
   whose kind (identity facts when on, else the entity type) is product, software or project, not a generic word;
   specific to the track (≥ 25% of all posts naming it are the track's judged-in posts: a platform, a language or an OS
   every post names is not); voices by Mark X's voice rule; the panel needs 2+ voices and one post where it is the
   subject, actor or compared; linked to `/markx/entities/{id}`.
5. **The class fix**:
   - **judge** `track-v2` (`markx/guides/track-v2.md`, the `track` kind's guide; v1 stays loaded for its open
     questions): a post about a tool of the kind the description asks for (its release, feature, demo, use) is in
     without step-by-step detail; "news about a company" is business news only. New questions only: no verdict is
     asked again until a track's description changes.
   - **finders** (`markx/finders.py`): a fourth finder `tool` (a passive post naming one of the tools 2+ voices of the
     track discuss: `track_tools.finder_ids`), and the domain finder taught by the track's own posts in (Haiku's in at
     ≥ 0.8 from its sources, or joined; the newest 200) besides the owner's ✓. The words stay the owner's ✓ only
     (measured below); the probe bar stays the ✓'s.
   - **source suggestions** (`tracks.suggestions`): a passive source is suggested when ≥ 10% of its posts of the 30
     days are in the track's sphere, ranked by the Wilson lower bound of that share (the line: "4 of its 12 posts in 30
     days are your …").
6. **Shadow**: sub-topics, digests and the tools panel are shown labelled with their measure (`page.shadow`, the UI's
   "Shadow: 79% of posts in the right sub-topic (157 of 200 checked)") and act on nothing; none passed the bar.

Frontend: `TrackTopic.tsx` (Tools, sections with state, fold, digest with citations, new markers, mark seen, Shadow
lines), `trackWords.ts` (baseline, newSince, isNew, trackNewLine, stateWords, toolLine, shadowLine, the share
suggestion), `services/tracks.ts` (types, `seen`, `look`). Design: `design/docs/pages/reader.md` (View topic, 0207).
Worker: `subtopic_place` and `digest` in `DEFAULT_KINDS`, one a call.

## Measured

Local reproduction on a scratch clone of `prep_mxreal` (posts to 5 Nov): the agent-workflows track with the owner's
new definition and 3 of its 4 active sources (the 4th is newer than the copy), and a local-setups track with one active
source; judged by the real worker (Haiku, $1.15 for 8,980 track-v1 questions); 1,019 posts in the two tracks, 12
sub-topics each. Blind labels by agent labellers who saw no verdict. Bar: 97% with a Wilson lower bound ≥ 90%.

| what | sample | result | Wilson lower | decision |
|---|---|---|---|---|
| auto-join: passive `in` at ≥ 0.85 | 100 (+30 out mixed in) | 77/100 | 0.678 | stays off (owner-label bar as before) |
| auto-join at ≥ 0.9 | 34 | 28/34 (82%) | 0.665 | off |
| judge v1 vs v2, tool-ish + other posts | 100, 2 labellers (91% agree) | agreement 83→87 (A), 80→86 (B); precision 0.55→0.63 / 0.52→0.63; tool-post recall 0.78→0.89 / 0.63→0.88 | — | **v2 adopted** (Discover routing, not auto-applied) |
| finders on held-out tool posts (34 agent tools the owner did not name, 957 candidates, 100 labelled, 40 in) | 40 in | recall 29/40 (72.5%) → 32/40 (80%); fired on outs 23/60 → 26/60 | 0.572 → 0.652 | **adopted** (nominations, the judge decides) |
| finders over the whole history | 17,228 posts | 4,828 → 5,843 put up (+21%) | — | cost below |
| words taught by the track's own posts | — | the 30 words were its sources' language stems; +72% nominations | — | **not adopted** |
| sub-topic membership, vectors only | 100 | 59/100 | 0.492 | replaced by Haiku placement |
| sub-topic membership, Haiku placement | 200 (2 labellers, 87% agree) | 157/200 (79%) | 0.723 | **Shadow** |
| digest points supported by their citations | 64; 88 after the guide's dates/attribution rules | 54/64 (84%); 73/88 (83%) | 0.736; 0.738 | **Shadow** |
| tools panel right for the track | 48; 27 with the subject rule | 32/48 (67%); 23/27 (85%) | 0.525; 0.675 | **Shadow** |
| stability, week-to-week replay (8 weeks, vectors only, no Haiku pins) | 1,004→1,546 and 392→1,343 posts | posts keeping their sub-topic id: 85.1-99.5% (agent workflows), 84.0-99.7% (local setups); new sub-topics appear (11→12, 7→12), none closed | — | — |

Generic sources no longer suggested (server shares, 30 days): a subreddit 4.3%, an all-posts blog feed 1.6%, an
aggregator 1.0%, a forum 0.4%; on the local copy the first suggestions became a code-trending feed (36%) and four
practitioners (29-37%).

**Memory and time** (jobs process, fresh, peak RSS): the local tracks job (place, cluster both tracks, keep the
pages) 1.5-1.9 s, 72-78 MB; on `prep_scale` (4 tracks) 3.6 s, 97 MB; a stress of one track with 5,107 posts in it:
25.4 s, 97.5 MB (the seed pool capped at 600 posts: 127.8 s before). The API is unchanged: the page is kept bytes;
`/seen` is two indexed reads.

**Worker cost a day** (measured per call on the local run: digest $0.0011, naming $0.0013, placement $0.0016 per 20
posts, judge $0.00012-0.00013 a post): digests at most 2 a day per changed sub-topic (~50 sub-topics: ≤ $0.11/day);
placement of new in-track posts (~40 a day a track: ~$0.013/day for 4 tracks); naming ≤ $0.01/day; the tool and domain
finders +~21% judge questions (~$0.2/day on a track judging ~$1/day). One-off: placing the existing in-track posts
(~$0.025 a track) and, when the owner sets the new definition, the description's new version re-judges its posts
(~$5-7 for the agent-workflows track at its measured cost).

## Tests

`test_track_subtopics_0207` (15): kinds, guides, planners; the target; naming, placement and digest answers checked;
what teaches the finders; groups appear, keep their ids, a new one appears, quiet fades last, an emptied one closes;
too few posts: none; the owner's rename, merge, split kept by the clustering and given to the judge; named once, not
over the owner, renamed on drift; Haiku's placements and "none" kept by the clustering; a digest with citations mapped
to posts, asked again only when its newest posts change; looks and joined times; tools by voices and specificity, the
tool finder, an owner ✗ drops it; domains taught, words not; suggestions by share. Updated: `test_markx_tracks`
(0145's sub-topic tests moved), `test_markx_finders`, `test_markx_validate`, `test_markx_storage`,
`scripts/tests/test_markx_worker.py`. Frontend: `tracks0207.test.tsx` (words; the view: digest citations, tools,
new markers, mark seen, quiet folded, Shadow lines); `tsc --noEmit` clean.

## Not done

- The owner's new definition is not set on the server (no writes there): the server track keeps its description
  until the owner edits it; track-v2 applies to new questions and to every post once the description changes.
- Auto-join stays on the owner's labels: Haiku's passive `in` measured 77% at ≥ 0.85.
- Sub-topics, digests and the tools panel stay Shadow (79%, 83%, 85% against 97%); each needs a better signal (a
  second placement opinion, a stricter digest check, the identity facts' `what` for tools) and a new blind sample.
- Discover's order (confidence, then date) still puts year-old 0.95s above this week's 0.9s.
- Not measured on the server's own posts (only GETs there); the local copy ends 5 Nov and lacks one active source.
- realdata-check: not run (the release's one run on main).
