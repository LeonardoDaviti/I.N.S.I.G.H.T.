# Design Studio — one structured home for INSIGHT's design

Status: **approved** (owner "go", 2026-10-10). Built on the integration branch `design-studio`; issue 0003 is folded in as slice S7.
Related: `plan/INSIGHT_mark_ix_design.md` (today's design language), `.claude/skills/{apple-design,emil-design-eng,break-ui}`, `plan/issues/`.

## Problem

- **The design knowledge is scattered across four places:**
  - `plan/INSIGHT_mark_ix_design.md` (261 lines: principles, tokens, history and a lead review all mixed together);
  - `FRONTEND_UI_GUIDE.md`;
  - `FRONTEND.md`;
  - "as-built" notes inside the specs.
- **Nothing ties a page to its design.** Nothing says which states a page must handle, and nothing fails when a page changes without its doc.
- **Experiments are expensive.** A layout idea means editing the real page, deploying the preview and judging it on live data. Rejected ideas leave residue.
- **Result:** slow experiments, drifting principles, and bloat creeping in one "small" change at a time.

## Goal

A single **Design Studio** at `/design` that holds:
- the principles;
- the system (tokens, type, motion);
- every page, rendered live in each of its states;
- the prototypes.

It is backed by plain markdown and TSX files in the repo, so agents and git diffs read exactly what you see.

## Decisions

### D1 — One source, two views
- The docs are markdown files in `frontend/src/design/docs/`.
- `/design` loads them with `import.meta.glob('…/*.md', { query: '?raw' })` and renders them with the app's own `MarkdownRenderer`, which already supports GFM tables.
- No CMS, no database, no backend endpoint. Editing a doc means editing the file.

### D2 — One home for design rules
- The binding parts of `plan/INSIGHT_mark_ix_design.md` move to `frontend/src/design/docs/system/`: principles, tokens, typography, space, motion, materials, status vocabulary and information architecture.
- The history (the reference study, the restyle checklist, the lead review) stays in `plan/`, under a header saying "archive; the live rules are in /design".
- `FRONTEND_UI_GUIDE.md` is folded in and becomes a one-line pointer.
- After this, a design rule exists in exactly one file.

### D3 — Studio sections
`/design` has a left rail, like the reader rail, and a centred doc column. Specimens may use the full width.

| Section | Route | What it holds |
|---|---|---|
| **Principles** | `/design` (home) | The constitution: at most 12 numbered rules (P1…P12). Each is one sentence, a *why*, and one do/don't pair. Every other doc and prototype cites these numbers. Changing a principle needs the owner. |
| **System** | `/design/system` | Tokens rendered **live** from the CSS custom properties (read with `getComputedStyle`, so they can't go stale), the type scale, spacing, radii, motion (a replay button that respects reduced motion), the status glyph vocabulary and icons. |
| **Components** | `/design/components/:name` | Each `components/ui` primitive in its variants and states. Each has a small hand-written specimen file. **No Storybook**: no new dependency. |
| **Pages** | `/design/pages/:page` | One entry per page in use (see D5): the page doc plus **specimens**, i.e. the real page component rendered in a frame per state. |
| **Prototypes** | `/design/prototypes/:id` | Experiments shown side by side with the current page, on the same sample data and widths. See D6. |
| **Parked** | `/design/parked/:page` | The analysis pages hidden while `INSIGHT_ANALYSIS=off`: one paragraph each (purpose, why parked, what the owner liked), plus a specimen where sample data already exists (inbox, experts, stories, post analysis). No full docs. |
| **Decisions** | `/design/decisions` | An append-only log, one line per design decision: date · page · decision · principle · link. It replaces the scattered "as-built" design notes. |

### D4 — Specimens show the real page on sample data, never the live API
- **Frames:** a specimen is an `<iframe>` pointing at a chromeless route, `/design/frame/:page/:state?theme=dark|light`. Its width is set by the studio (1400 / 390, or free). The page gets a real viewport, so Tailwind breakpoints and `100dvh` behave exactly as on a device.
- **No live API:** before rendering, the frame replaces **its own** `window.fetch` with a fixture transport for that state. Every API call goes through `fetch` (`services/api.ts`, `services/trackApi.ts`), so the page code doesn't change at all. The studio window's own `fetch` is never touched.
- **State tricks:**
  - *loading* is a promise that never resolves;
  - *error* is a 500 response with a long message (break-ui);
  - *empty* is an empty list;
  - *worst* uses the break-ui catalog rows that apply to the page.
- **Unmatched requests:** any request with no fixture renders a visible "unmocked request: GET /api/…" bar inside the frame. Gaps show up immediately.
- **Shared fixtures:** the studio and the tests use the same files (`*.fixtures.ts`, `components/*/fixtures.ts`). What you see in the studio is what the tests assert.

### D5 — Pages in use, and their states

| Page doc | Covers | Required states |
|---|---|---|
| `reader` | `/` and `/read/:kind/:id` (all / track / source), filters unread · starred · all | normal, empty (nothing unread), empty scope, loading, error, worst (long titles, non-Latin, RTL, 1,000+ items) |
| `post` | `/posts/:id` | article, images and video, long title (wrap), h1–h6 scale, missing title (Telegram), loading, error |
| `sources` | `/settings/sources`, tabs **sources · connections · ingestion** (overview / jobs) | dense list, search with no hits, bulk selection, source sheet, connections set / unset / expired, ingestion run report partial-failure, scheduler not running |
| `shell` | top bar, ⌘K, keyboard help, dialogs and sheets | ⌘K with many tracks, narrow (320px) top bar |

**The track page is retired into the reader (decision).**
- `/tracks/:id` and `/read/folder/:id` render the same posts, with two components to keep in sync. Since S6 (fetching left the reading views), `TrackPage` adds nothing the reader lacks.
- `/tracks/:id` redirects (replace) to `/read/folder/:id`, and the ⌘K "Tracks…" entries point there too.
- With analysis on, the track briefing and milestones still have a home: they render in the reader when its scope is a folder. That's the same place, so analysis-on behaviour is unchanged.
- One page fewer to design, test and document (P: one place per job).

### D6 — Prototypes
- **Location:** `frontend/src/design/prototypes/<yyyy-mm-dd>-<slug>/`. Each holds:
  - `README.md`: the hypothesis (one sentence), the principle(s) it serves, what changes versus the current page, and its status;
  - `index.tsx`: the prototype, a component that may import anything from the app.
- **Registry:** `import.meta.glob`. Adding a folder registers the prototype; there is no list to edit.
- **Compare view:** current page ⟷ prototype, in frames with the same state, theme and width.
- **Lifecycle:** `draft → review → accepted | rejected`.
  - *Accepted:* ported into the real page and the page doc in one commit. The folder is deleted and a line goes into the decisions log.
  - *Rejected:* the folder is deleted and the log keeps one line saying why.
  - The studio home lists open prototypes with their age, so nothing rots silently.
- **Isolation:** prototypes never change production pages and never call the live API, because they render in frames (D4).
- **Seed prototype:** the pending **post-title wrap** question. Two variants side by side: current `pretty` (82% first line, no one-word last line) versus `normal` wrap (≈90%, may leave a one-word last line). The owner decides by looking.

### D7 — Rules that keep the docs from bloating (written into the Principles doc as "How we change the design")
1. **Small changes:** any UI change that alters layout or flow starts as a prototype. Copy and spacing fixes go straight into the page doc and the page, in the same commit.
2. **Cite a principle:** every change cites at least one principle. If none supports it, the change isn't made, or the owner discusses the principle.
3. **Docs describe what is.** A page doc's "As-is" matches the shipped page. Proposals live only in prototypes, never as prose in the doc.
4. **Fixed template**, max ~150 lines per page doc:
   - Purpose
   - Entry & URL
   - Anatomy
   - States
   - Interactions & keys
   - Worst cases
   - A11y & motion
   - Decisions (links into the log)
   - Open issues (links into `plan/issues/`)
5. **Size limits:** the Principles doc fits on one screen.
6. **Coverage test** (vitest), which fails the build when:
   - a route in `App.tsx` has no page doc, no parked doc and no redirect entry;
   - a page doc has no specimen for one of its required states;
   - a doc cites a principle number that doesn't exist.

### D8 — Access and cost
- **Where it appears:** `/design` is not in the top bar. It's in ⌘K as "Design studio", and works with analysis on or off.
- **Bundle:** it's a lazy route chunk. The reader's initial JS must not grow by more than 1%, and a build check asserts it.
- **Look:** the studio follows its own principles: monochrome, reading-first, quiet chrome.

### D9 — Screenshots
- **Not committed.** The studio renders live, so stored PNGs would only go stale.
- `npm run design:shots` (Playwright, the dedicated browser at `~/.cache/insight-pw`) writes every page × state × {1400, 390} × {dark, light} to `frontend/.design-shots/` (git-ignored). Agents and the owner use it for before/after reviews.

## Out of scope
- Visual-diff CI (it can come later on top of D9).
- Editing docs from the browser (the files stay the source).
- Redesigning any page. The studio documents what is shipped; changes go through prototypes afterwards.
- Building anything from `plan/issues/0001`, `0002` or `0004`.

## Slices
1. **S1 — Docs and the coverage test:**
   - write `principles.md` (P1–P12 distilled from design doc §2 and the owner's feedback this week: monochrome, reading-first, centred, icons not words, no metadata noise, fetching belongs to Sources, hide don't delete…);
   - add the `system/*`, the four page docs, the parked docs and `decisions.md` (seeded from this week's decisions);
   - archive the old design doc;
   - add the coverage test (routes ↔ docs).
2. **S2 — Studio shell:**
   - the `/design` lazy route, rail and markdown rendering;
   - the ⌘K entry;
   - the live token, type and motion specimens;
   - component specimens;
   - the bundle-size check.
3. **S3 — Frames and specimens:** the chromeless frame route, the fixture transport (D4), the state matrix for reader, post, sources and shell, the width and theme toggles, and the unmocked-request bar. Extends the coverage test to specimens.
4. **S4 — Prototypes:** the glob registry, the compare view, lifecycle states and the open-prototype list. Ships the seed **title-wrap** prototype.
5. **S5 — Retire `TrackPage` into the reader:** the redirect, ⌘K links, the folder-scope briefing and milestones when analysis is on, and tests. Update the reader doc and log the decision.
6. **S6 — `design:shots`:** the Playwright script.

S1 comes first. S2 and S5 can run in parallel. S3 needs S2, S4 needs S3, and S6 needs S3.

## Acceptance (owner-visible)
- `/design` opens on the principles. You can reach every page in use and see it in each state at phone and desktop width, dark and light, without touching real data.
- The title-wrap prototype sits next to the current title. You pick one, and the choice lands in the decisions log.
- `/tracks/:id` opens the reader scoped to that track.
- Removing a page's doc, or adding a route without one, fails `npm test`.
7. **S7 — Issue 0003:** source and track names link into Sources (`?source=` opens the sheet, `?track=` scrolls to and highlights the group; unknown id shows a quiet note). Runs with S5.
