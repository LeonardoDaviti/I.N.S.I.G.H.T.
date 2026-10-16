```meta
kind: log
```

# Decisions

Append-only: one line per design decision, newest last. Never edit or delete a line; a reversal is a new line that names the one it reverses. Format: `id · date · page · decision · principle · link`. Rejected prototypes get a line saying why (D6).

- **001** · 2026-10-09 · all · Mark IX is monochrome: black and white only like news.smol.ai, dark by default, light the same system inverted. · P2, P3 · `plan/INSIGHT_mark_ix_design.md` (archive), commit 206e224
- **002** · 2026-10-10 · shell · The Mark VIII hub is deleted: `/` is the reader, `/hub` redirects home, navigation is one top bar. · P1 · commit 168c09c
- **003** · 2026-10-10 · all · Reading-only app (spec §9): analysis surfaces are hidden behind `INSIGHT_ANALYSIS` (default off), not deleted; the top bar is `feed / sources`. · P1, P10 · `plan/INSIGHT_mark_ix_reading_finish_plan.md`, commit 9a51f95
- **004** · 2026-10-10 · post · The post is one centred column with three icon actions (↗ ☆ ⧉) beside the title and no machine metadata. · P4, P5, P6 · commit 9a51f95
- **005** · 2026-10-10 · sources · Ingestion is a tab under Sources; `/ingestion` redirects there reading-only. · P7, P9 · commit d304422
- **006** · 2026-10-10 · shell · The `/tracks` list is dropped reading-only; ⌘K lists one entry per track instead. · P9, P10 · commit efa0ce5
- **007** · 2026-10-10 · reader · Fetching leaves the reading views: no fetch button or key in the reader or the post; an empty scope points quietly to Sources. · P7 · commit 30eb7b1
- **008** · 2026-10-10 · sources · Secrets live only in Sources → Connections, never in `.env` or the environment. · P7 · commits aa8fddc, 114e37d
- **009** · 2026-10-10 · design · The Design Studio: design rules live once, in `frontend/src/design/docs`, shown at `/design`. · P9 · `plan/INSIGHT_design_studio_plan.md`
- **010** · 2026-10-10 · reader · The track page is retired into the reader: `/tracks/:id` redirects to `/read/folder/:id`; with analysis on, the track briefing and milestones render in the folder scope. · P9 · design studio plan D5 (S5)
- **011** · 2026-10-10 · reader, post, sources · Source and track names in reading views link into Sources (`?source=<id>` opens the sheet, `?track=<id>` highlights the group). · P8 · `plan/issues/0003-source-name-opens-source-settings.md` (S7)
- **012** · 2026-10-11 · design · The studio keeps all three prototype variants as modes of one studio: Handbook (default), Wall and Bench, switched by a segmented control and ← →; it is reached from ⌘K only. · P1, P9 · `plan/INSIGHT_design_studio_plan.md` (prototype verdict)
- **013** · 2026-10-11 · design · Specimen frames render the real page inside the real shell, top bar included, so a frame (and the Wall) reads like the site; the frame has its own router, storage, theme and fixture `fetch`. · P1, P9 · `src/design/frame/FrameRoot.tsx` (S3)
- **014** · 2026-10-11 · design · The Wall draws the whole site as one site map from `wall/siteMap.ts` (pages, labelled moves that use the app's own hrefs); P-chips light the pages whose doc cites a principle; the walk replays the owner's journey in one interactive frame with real clicks, on fixtures, at real speed. · P1, P8, P9, P12 · `src/design/modes/WallMode.tsx` (S4)
- **015** · 2026-10-11 · blog · The blog lives at `/blog` (top bar word `blog`): posts are lessons from INSIGHT's own code, written plainly with every claim cited, and every post carries figures, inline monochrome SVG of measured numbers, because the owner finds them what makes a post worth reading; code excerpts are real, captioned and highlighted by weight and tone only. · P2, P3, P11 · `pages/blog.md`, commits 790311a, 9e3e115
- **016** · 2026-10-11 · all · Reverses 003 and rewrites P10: analysis is retired, not hidden. Its code goes to a git tag, its ideas stay as issues (0001, 0002, 0004), and better analysis is built later as new work. · P10 · `plan/issues/0005-minimal-codebase.md` (owner, 2026-10-11)
- **017** · 2026-10-11 · design · Bench is the checkout for a design change: a prototype is a folder `prototypes/<date>-<slug>/` found by glob (README meta, `index.tsx`, optional `doc.diff`), compared in Bench against the current page on the same state, width, theme and data; accept and reject are instructions to the agent, never browser writes. · P9 · `src/design/prototypeRegistry.ts`, `src/design/modes/BenchMode.tsx` (S5b)
- **018** · 2026-10-11 · design · `npm run design:shots` screenshots every page × state, every prototype × its states and the studio's own modes, and fails on a frame that never gets ready, shows an unmocked request or logs an error; the shots are not committed. · P11 · `scripts/design-shots.mjs` (S6)
- **019** · 2026-10-11 · design · principles.md keeps each principle as its one-line rule (numbers and rules unchanged), within 40 lines and 450 words; the why, do and don't of each move to `system/principles-explained.md`. · P9 · `src/design/coverage.test.ts`
- **020** · 2026-10-16 · post · Supersedes 011 for the post byline: the source name opens the reader on that source (`/read/source/<id>`) and a quiet ` / settings` beside it opens the source sheet; the reader's header title still links to Sources. Post navigation is a sticky band under the top bar and repeats after the article. · P5, P8 · `plan/issues/0010-post-page-navigation.md`
- **021** · 2026-10-16 · post, reader · Continuous reading is the default: on a post page the feed's next posts follow below, the post at the midline is current and owns the URL (replaced), a post is read once its end passes the top half of the screen, and `Posts continuous / one at a time` in the reader toolbar turns it off. · P1, P4, P12 · `plan/issues/0014-continuous-reading.md`
