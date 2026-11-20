# 0245 — Track briefings: the things a track is about, pulled out of its posts and read as a briefing (v10.27 plan)

Status: **accepted** (owner 2026-11-20), one general briefer for every track (memory `track-briefer-general`); experiment rounds 1-2 in `plan/research/briefer-0245/` (private). Deepens 0207 (sub-topics, digest per sub-topic, new since you looked,
tools in use) and answers 0002's reading feedback. No code yet. Real rows behind the examples are private
(`plan/research/v1026/`); the examples below are the kind of rows the server's tracks hold today.

## Why

A track today is 1:1: Haiku judges whole posts in or out, gives each a sub-topic and a one-line "why". The reader can
browse but cannot compare or ask: "what runs a 27B model under $1,500", "kitchen prints in PETG with no extra
hardware", "new agent skills this week". The facts are in the posts (and often already in the "why" lines) but not as
fields. A post about a whole build often holds one thing the track wants (a printable part, a setup, a tool).

## What the reader gets

1. **Things, not only posts.** Each track has a few *kinds of thing* it is about, each with fields:
   - Local Setups: **setup** (hardware, cost, model, quant, engine, speed, memory), **release to run** (model,
     size, runs on, quants), **engine change** (engine, version, what changed).
   - Cool Projects: **project** (what it does, built with, licence, repo, maker, why it's cool).
   - 3D Projects: **print** (what, category, files link, material, printer needs, extra parts, why print it),
     **printer/slicer change**, **test result** (what was tested, materials, numbers, verdict).
   One post can give several things or none; one thing reported by many posts is one row with all its links (the
   one-release-one-row rule, at the level of things).
2. **A briefing per track:** "what changed" (2-4 points with quiet citations), then the new things by kind, then the
   posts. Kept as weekly **issues** (the date strip 0002's owner feedback kept), never deleted.
3. **Asking:** filter chips built from the fields (price under, runs on, material, licence); later a question in words
   answered from the rows with citations (0098).

## When and how the reader reads it (the UX)

Three reading moments, one page.

**A. The quick look (daily, 1-3 minutes, phone or desktop).** Opening a track shows what is new *since you looked*
(0207's seen state), nothing else first:

```
Local Setups                                   since Tue · 6 new
──────────────────────────────────────────────────────────────
What changed
• NPUs became a real option: Unsloth Desktop runs models on
  AMD XDNA 2 NPUs at 2-4x less energy per token.  ²
• llama.cpp v1.0: MoE offload with an LRU cache sized to VRAM. ³

New setups (2)                                         see all ›
  4x Radeon R9700 · QFN 3.8 · prefill/latency/cost given    ↗
  Xeon + GTX 1070 · ~43k RUB · 125B MoE · 14-15 tok/s        ↗
New to run (1)
  Qwen3.8-27B GGUF UD V3.1 · RAM/VRAM table                 ↗
──────────────────────────────────────────────────────────────
Posts (6 new) ▾
```

- "What changed" is at most 4 short points, each a sentence; citations are small superscript links to the posts (no
  "(Post 16)" text: 0002). Opening it marks the track seen.
- Nothing stale on top: if the points are older than the newest post, they say "as of Tue" and the new posts show
  first (0002's staleness rule).
- Nothing new: one line "Nothing new since Tue" and the last issue below, folded.

**B. The weekly read (weekend, 10-20 minutes, desktop or tablet).** The **issue** for the week: a page you read top to
bottom, like a newsletter you wrote for yourself.

```
3D Projects · week of 13-20 Nov                 ‹ 6 Nov   13 Nov   20 Nov ›
What changed
• Two kitchen prints worth making; a new offline CAD tool.  ¹ ²
Worth printing (4)                         [PETG] [no hardware] [kitchen]
  Print               Material  Needs         Extra parts   Why
  Kitchen timer dial  PLA       standard bed  timer mech.   replaces a clunky timer   ↗
  Portafilter key     ABS       standard      —             a daily small fix         ↗
  Bike basket posts   PETG      standard      plywood, M4   beats a $7 basket         ↗
Printer & slicer
  Bambu firmware … · Prusa … · (one line each)                                       ↗
Tests
  PLA vs PETG at 3 infills · numbers · verdict                                       ↗
Workshop tools
  DabbleCAD · offline CAD for printing and laser cutting                             ↗
```

- Tables on desktop; on a phone each row is a card (title line, 2-3 facts, the link).
- A row opens its thing: every post that reported it, the facts with the post each fact came from, and its entity page
  when it is one (a model, an engine, a printer).
- The issue is frozen when the week ends (keep everything); a correction later is shown as "updated".

**C. The intent moment (when you are about to buy, print or try something, any time).** The track's **tables**:
all rows of a kind across all issues, sortable and filterable by the fields, newest first.

```
Local Setups › Setups (37)        [under $1,500] [runs 27B+] [Apple Silicon] [+ filter]
```

- Filters are the fields' own values (money ranges, model size buckets, hardware family, material).
- A question box later ("what runs a 27B model at 30+ tok/s under $1,500?"): answered from the rows, every claim
  cited, "not in your sources" when the rows can't answer.

**Where it sits.** Tracks stay in the reader rail (navigation.ts). A track's rail entry shows a count of new *things*
(not posts) when there are any ("3 new setups"). No push notifications in v10.27. The issue strip lives on the track
page; the News tab is unchanged.

**What the reader controls.**
- The kinds and fields: proposed from the track's description once (Haiku), shown as a short editable list ("Setup:
  hardware, cost, model, quant, engine, speed, memory"); the owner adds, renames or removes a field. A field change
  re-reads only the posts already in the track.
- A wrong fact or a wrong row: one tap "wrong" on the fact (stored as a label, as News's one tap), and I review flags
  first (claude-reviews-entities-first).

## How it is built (in the modules that own it)

- **Kinds and fields per track:** stored with the track (`tracks` / track settings), versioned like the description
  (a version bump re-reads).
- **Extraction:** a worker kind `track_things` (Haiku, guide `track-things-v1`), asked only for posts already in the
  track (judged in, joined or pinned): the post's text + the track's kinds and fields → things found, each field with
  the quote it came from (validate.GUIDE_CHECKS: every value's quote is in the post). Its answers are kept as calls
  (mx_tasks/mx_calls, like every kind); the rows a briefing reads are the *things*, one table `mx_track_things` (new:
  a thing outlives a post and merges many posts' reports; justified as stored state, not a cache).
- **One thing, many posts:** the same thing reported twice is joined by its key fields (a model + quant, a repo, a
  print's files link) and by the entity it names when there is one (identity: a model, an engine); never by a vector
  alone.
- **"What changed":** 0207's `digest` kind deepened (one kind, not a second): over the new things and new posts since
  the last issue, 2-4 points citing them; asked again only when they change.
- **Issues:** a week's issue = the track's things and points as of the week's end, kept (a kept page per issue,
  kept_pages, built in the jobs process, never on an open).
- **Seen:** 0207's `mx_track_seen` (per track and sub-topic) also counts new things.
- **Cost:** one question per post in the track (Local Setups ~160 posts so far, a few a day; 3D 10; Cool Projects
  ~5 a day) and one digest a track a day at most: cents a week.

## Bars (no-owner-label-gates: automatic above a bar I measure blind)

- Things right (a real thing of that kind, in the post): point >= 97%, Wilson lower >= 90% on a frozen held-out set,
  two blind Haiku labellers, a referee on splits.
- Fields right (value correct and quoted): the same bar per field kind; a field under its bar is hidden, the row stays.
- Joins right (two reports are one thing): the same bar; under it rows are not joined.
- "What changed" points supported by their citations: the same bar (0207's digest was 73/88: the guide must change).
- Each part ships ON when it passes, OFF when it fails (new-tech-on-in-production).

## Order

1. **Local Setups first** (the clearest facts, 160 posts): kinds and fields, extraction, tables, the quick look.
2. **Cool Projects** (projects from GitHub Trending + the Discover lane; also ties its high-fit sources to the track).
3. **3D Projects** last: it has 10 posts; first more 3D sources (the 7 added 2026-11-19, Printables and MakerWorld
   through v10.26's scraping, r/3Dprinting and r/functionalprint once Reddit reads on the server), then calibrate its
   in/out (2 of its 10 posts are wrong), then fields.
4. The weekly issue and the issue strip, once two tracks have things.
5. Questions in words (0098), after the tables.

## UX decisions (made by me 2026-11-20 at the owner's request; the owner will re-edit later)

- **The issue's week is Monday-Sunday**, built Monday morning. A fixed week makes issues comparable, and the date strip stays stable ("week of 16 Nov"). "Since your last read" is already the quick look (moment A), so the two moments don't overlap.
- **The rail count of new things is on for every track** that has new things, and silent for the rest. It counts things, not posts, and is capped at "9+". A track you haven't opened in 30 days drops its count, so the rail doesn't nag.
- **Phone: both.** The quick look is designed for the phone first. On the phone the issue is a stack of cards (one per thing) with the "what changed" points on top. The full tables and filters (moment C) stay on desktop and tablet; on a phone they open as a filtered card list.

## The general design after the experiment (2026-11-20, rounds 1-2 on all 4 server tracks)

Measured on 55 posts, every track the same code: round 2 recall 59 of 91 facts (65%), values 88 of 94 right (all 4
wrong ones the prototype's number parser, none Haiku's), numbers/links/choices the same on a second run 80%, one run
of all 4 tracks $0.058. The design that ships:

1. **Schema from the description only.** Haiku proposes the track's kinds and fields; code always adds the general kind
   **practice or claim** (what, result, evidence). Text values capped at 120 characters.
2. **Typed values from Haiku, checked by code.** Each number comes as `{number, unit, currency, range_to}`; each link as
   a URL. Code checks the digits (or the URL) appear inside the value's own quote, and the quote in the post. No
   free-text number parsing in code.
3. **The post's own address is attached by code**, never offered to Haiku as a candidate link; a link field is an
   external link in the post.
4. **Long posts read in several windows** (the readings' units), merged per post; Haiku is asked for every field of a
   kind, so an empty field is a decision.
5. **Joins:** things by key fields (a link, a model and quant, a repo) or the entity they name; practices by a shared
   entity, then one Haiku "same claim?" question for those pairs only; never by similarity alone.
6. **The brief:** "what changed" points are about things and practices only (never authors or sources), each citing
   rows; counts and section headers written by code; posts that gave no row listed under "Also in the track".
7. **Bars:** values >= 97% right (Wilson >= 90%), recall >= 85% for the first version, joins >= 97%, points supported
   by their rows >= 97%; measured on a frozen held-out set across all tracks, never one track.
