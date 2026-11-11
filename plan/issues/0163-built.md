# 0163 — Built (Stealth v10.13.11): Later developments, in Shadow

Built 2026-11-11 on its own branch, test-first, parts A–E of the [spec](0163-later-developments.md). **Migration 0102.**
Not on News: the measure (spec, "Measure") is not run yet.

## What was built
- **`markx/later.py`** (new):
  - **A. Long-lived stories.** A Mark IX story of 2+ sources whose subject is a `paper`, `document`, `model`,
    `software` or `dataset` (`method` too, once 0151's types add it). The subject is back's E subject (the subject
    mention of 2+ members, of 1 when only one was read), counted two ways: by entity (its root through the merges, a
    pin first; an entity marked not one is none) and by name key. Every other story keeps back's once-only trigger.
  - **B. The follow-up trigger** (no model, one source enough, no age limit). A post dated after the story's last
    post (the reader's date), not a member, not saved, not one of the story's own sources carrying a member's page:
    - **E:** its own subject mention (role `subject`) is the story's subject entity, or has its name key, or, when the
      subject names a version, is a later or the same version of its family (`family_key` equal, version tuple at or
      after; a subject with no version matches only itself);
    - **L:** it is or links one of the story's pages (back's: members' addresses, pages 2+ members link, the origin;
      hubs out) or an address of the subject (`mx_entity_addresses`, through the merges, while its post still names
      it). Pages compare by `back.norm`, a paper's by its identifier (`entity_originals.paper_ref`): the arXiv abs,
      html, pdf and vN forms are one page.
    - V alone never.
    - One row a (story, post) in `mx_later`, with the subject entity it was found for (the entity page reads it).
  - **Bounded:** each run reads the posts dated since its clock less 1 h, oldest first, at most `PER_RUN` = 5,000.
    A run that hits the cap keeps the last (date, post) it read and the next reads on past it, so a backlog never
    stalls on many posts of one date. The first run reads 30 days back, 5,000 posts a run.
  - **C. The judge:** the frozen `back` guide, its input `back.render` (the story's 4 earliest posts, then the new
    post), RUNS = 3, the majority. Planned after back's own questions under back's cap (`Config.back_open`, open or
    leased `back` tasks, shared), newest post first; also from the lease (`tasks._plan_back` plans both). Every
    verdict is stored (`settle`, at most 500 a run); the pages read a fresh one live before it is stored.
  - **D.** `of_story` (a Mark IX story id, or a Mark X story id: the Mark IX stories of its current members),
    `of_entity`, `label` (item_kind `later`), `precision`, `follow` (Stop following / Follow again: a row each time).
    `NEWS_KEY` (`later_news` in mx_settings) is the flag that will gate News; off, and nothing reads it as on yet.
- **`markx/back.py`:** a long-lived story still followed may fire again 30 days after its last `mx_back` window
  (`Story.again`); others fire once, as before. A stopped story never fires again.
- **`markx/decide.py`:** a `later` stage after `back` (its own timing line); its counts are in `counts.later`.
- **API** (`markx/later_api.py`, one include line in `api.py`): `GET /api/markx/later?story=<id>`,
  `GET /api/markx/entities/{id}/later`, `POST /api/markx/labels/later`, `POST /api/markx/later/follow`.
- **Frontend** (`components/markx/MarkXLater.tsx`): the Mark X story page's **Later** section (what it follows, Stop
  following / Follow again, the rows judged development, the rest folded with their verdicts, label buttons on each)
  and the entity page's **Later developments** (the same rows, each with the story it follows).
- **Migration 0102:** `mx_later` (unique story and post), `mx_later_stops`, `mx_labels.item_kind` `later`. Mark X
  tables only, no key to Mark IX or to `mx_tasks`; never deleted.

## Measured time (a synthetic copy at production size; no local copy has entities)
No local database has Mark X entities (`insight_server_1105_mxreal*` stop before 0072). A synthetic fixture: 100k
posts, 1M mentions, 50k entities (2k merges, 5.6k addresses), 10k Mark IX stories of 3 sources (5,554 long-lived),
120k links. It hits far more often than real data (4–7k Later rows per 5,000 posts), so it is a worst case.
- `long_lived` with pages and addresses: 0.8 s.
- First run (30-day backfill, 5,000 posts): 2.4 s; the next three backfill runs 2.4–2.6 s each.
- A steady run (2 h of posts): 2.0 s.
- Beside it, back's own stage (unchanged here) took 19 s on the same fixture, steady (its per-story loop over the
  73 h of posts). Not this issue's, but the next one to look at.

## Not as the spec reads
- **The backfill reads oldest first**, 5,000 posts a run, and resumes. The brief allowed newest first; oldest first
  needs no second clock and finishes the 30 days in a few runs.
- **Story pages compare by paper identifier too** (a story whose members link a paper's abs page finds a later pdf link).
- **Hubs apply to the story's pages only**, not to the subject's addresses: a paper linked for many weeks is just what
  a long-lived story follows.
- **Reposts:** a repost of a member is the member's own row (stored once), so it is out as a member. A story source's
  post carrying a member's own address is taken out as well.

## Tests
- `test_markx_later` (22, new): version order, a paper's forms; long-lived types; one-of-two read; E by entity id
  at 400 days, through a merge, a later version of its family and not an earlier one, a mere mention is not a
  subject; L by the subject's address in its pdf and html forms, a page two members link, a hub out; V alone never;
  members, saved, older posts and a story source's repost out; E and L together; Stop following and Follow again;
  the per-run cap and resume, never stalling on one date; the first run's backfill; planned under back's cap, asked
  three times, settled, shown (story and entity API), labelled; a Mark X story page; a second wave after 30 days for
  a long-lived story only, none once stopped; Mark IX only read.
- Updated: `test_markx_jobs` (the `later` stage), `test_markx_storage` (two tables), `test_markx_api` (MX_TABLES).
- Frontend: `components/markx/later.test.tsx` (4).

## Open
- The spec's measure (held-out mining, the weight-space gold, cost per day) before any News row.
- The owner's open questions 1–2 (a "Watch this story" notification; more long-lived types).
