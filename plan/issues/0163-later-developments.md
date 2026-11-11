# 0163 — Later developments: a story about a method, a paper or a model keeps gathering its follow-ups, at any age

Status: **spec** (2026-11-11). Stealth (Mark X, Shadow: mx_* rows only, Mark IX read). Builds on 0092/0136 (Back in the
news: its E/L/V hits and the frozen `back` judge), 0090 (entities: the subject mention, the specific types), 0125
(connections: a post's links in reverse), 0131 (the graph's edges).

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `markx/back.py` (module docstring: the trigger, the judge,
the row); `plan/issues/0136-built.md`; `markx/candidates.py` (the 72 h windows); `utils/story_rules.py`
(`LINK_WITHIN`).

**The owner (2026-11-11):** "for example [the weight-space programming story], someone tried this technique on some
model 77 days after its publishing, what will happen?"

**Constraints:** keep everything (rows added, never deleted); fix the class (no story, source or site lists); no real
names in committed files; Shadow only (mx_* rows, Mark IX untouched); unit tests + measured on held-out server
history; realdata-check once at release.

## Why: what happens today (from the code, 2026-11-11)
A single post 77 days after a story, naming its paper or method, is in the feed and on the paper's entity page, and
its page shows "refers back" when it links the paper (0125/0131). It never reaches the story:
- Mark IX joins within 72 h (`LINK_WITHIN`), same text within 30 days.
- Mark X candidates: post pairs within 72 h; story merges 14 days apart (a shared document: 30).
- Back in the news needs **2+ sources inside 72 h**, and a story fires **once** (`mx_back`): a lone follow-up never
  fires, and a second wave months later never fires again.

Production, 2026-11-11: 486 back candidates, judged 32 development, 48 retold, 209 related, 188 unrelated; the owner's
labels so far 4 of 11 development (36%) against the lab's 87%. **The judge is the weak part**: any widening must keep
its rows off News until measured.

What a technique story looks like: a paper or method (the weight-space story: 15 posts of one document entity in
8 days), then for months: people applying it to other models, replications, critiques, a v2, a library. Each a lone
post, often weeks apart.

## What it does
### A. Which stories keep listening ("long-lived")
- A story whose subject (0136's E subject: the ent-v3 subject of 2+ posts) is of a type that outlives an event:
  `paper`, `document`, `model`, `software`, `dataset`, `method` (the last when 0151's types add it; until then
  `other` with a `technique` role is not used). Events, launches of products, deals and people stories keep today's
  once-only Back in the news.
- No age limit. A story stops listening only when the owner says "Stop following this story" (a row, reversible).

### B. The follow-up trigger (no model; one source is enough)
A post of any age after the story's last post, not a member, is a follow-up candidate of a long-lived story when:
- **E'**: its own subject mention (role `subject`, not just a mention) is the story's subject entity, by entity id
  (aliases merged by 0090/0118), the same version or a later one of the same family; or
- **L'**: it links one of the story's own pages (members' addresses, pages 2+ members link, the origin; hubs out as in
  0136), or an address of the subject entity (0138 addresses: the arXiv abs/html/pdf/vN forms, the repo, the model
  hub page).
- V alone never: vectors find "same topic", which is the 209 "related".
- Saved posts and the story's own sources' reposts of members are not candidates (they are retellings).

### C. The judge
- The frozen `back` judge (back-v1) answers per post: development / retold / related / unrelated, RUNS=3, majority.
  Only **development** proceeds. Its question shows the story's 4 earliest posts and the new post (as today).
- Cost: E'/L' fire on far fewer posts than V; measured ceiling before build (below). Planned by the decision run,
  capped (`OPEN`) as back is.

### D. Where it shows
- **The story's page**: a "Later" section, newest first: date, "N days after", source, title, what tied it (names
  the paper / links it), and the owner's label buttons (development / retold / related / unrelated) as 0136's rows.
- **News**: not at first. A follow-up reaches News ("Back in the news: <headline> — <new post's title>") only when
  the measure below passes; until then, Shadow page only.
- The entity page of the subject lists the same posts under "Later developments" (read from the same rows).
- A second wave (2+ sources in 72 h, today's trigger) still makes a Back in the news row; for long-lived stories it
  may fire again 30 days after its last row (today: once ever).

### E. Rows
- `mx_later (story, post, trig {E,L}, found_at, task, verdict, label)`, unique (story, post); never deleted.
- Migration; repo functions; the decision run's `back` stage gains `later.find` + `later.plan` (bounded: posts since
  the last clock less a margin, as back's `since`).

## Measure (before News; held-out per the held-out rule)
1. Mine server history (posts before 2026-10-01 as stories, after as follow-ups) for long-lived stories: how many E'
   and L' candidates a week; the judge's verdicts; Opus-labelled sample of 100 (development / not) → precision with
   Wilson bounds, per trigger.
2. The weight-space case as the gold: every later post naming the paper or linking it is found; the "I applied it"
   posts are development.
3. Bar for News: development precision lower bound ≥ 80% on the held-out labels and on the owner's labels once 20+.
4. Cost per day (judge calls) at today's volume.

## Done when
- Tests: long-lived types; E' by entity id and version family; L' with address forms; V alone never; members,
  saved and reposts excluded; no age limit; "Stop following" row; the judge's planning cap; the Later section's
  API; a second wave for a long-lived story after 30 days; nothing written to Mark IX.
- Migration; the story page and entity page show Later (frontend builds, vitest); design docs claim the section.

## Open (the owner)
1. Whether a long-lived story's follow-ups should also notify (a track, 0145) — "Watch this story".
2. Which types count as long-lived beyond paper/document/model/software/dataset (e.g. a law, a standard).
