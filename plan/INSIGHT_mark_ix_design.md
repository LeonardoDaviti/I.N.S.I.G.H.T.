# INSIGHT Mark IX — Design language (archive)

> **Archive.** The live design rules are in `frontend/src/design/docs` (shown at `/design`):
> the principles in `principles.md`, the system (tokens, typography, space and layout, motion,
> materials, status vocabulary, information architecture, components) in `system/`, each page in
> `pages/`, and decisions in `decisions.md`. Sections 2–11 moved there on 2026-10-10 (Design Studio
> S1) so no rule lives in two places. What remains here is history: the reference study, the
> restyle checklist and the lead review.

Status: adopted 2026-10-09. Owner direction: "I don't like the Mark VIII hub at all, it's non user friendly."
Dark is **black and white only**, like news.smol.ai. Light uses the same monochrome system, inverted.
Until 2026-10-10 this document was the contract for every frontend slice (spec §F.6, §F.7). Implemented in
`frontend/src/index.css`, `frontend/tailwind.config.cjs`, `frontend/src/components/ui/*`,
`frontend/src/components/states/*` and `frontend/src/components/layout/*`.

Reference: `plan/design/reference-news-smol-ai-dark.png`. Before: `plan/design/before-mark-viii-hub.png`,
`plan/design/before-f2-health.png`. After: `plan/design/after-*.png`.

---

## 1. What we took from the reference

| Observed on news.smol.ai | INSIGHT rule |
| --- | --- |
| Near-black page (#171717), no gradients, no glow | `--bg` #121212, flat. Gradients are disabled in the Tailwind theme. |
| Inverted wordmark: white block, black text | `INSIGHT` wordmark is an inverse block, top-left, links to `/`. |
| Lowercase slash nav with underlines: `subscribe / issues / tags` | `feed / sources` (the five words `feed / tracks / briefings / sources / ingestion` with `INSIGHT_ANALYSIS` on), underlined, current item bold with a solid underline. |
| A `Search (Cmd+K)` box on the right | A `⌘K` quick switcher, **navigation only** (search stays deferred, spec §F.2). |
| Rows: 1px grey border, ~6px radius, muted date column, bold title, chevron | `Row` primitive: date/meta column in `text-3` tabular nums, title weight 600, chevron on hover-capable pointers. |
| A grotesk sans, generous whitespace, no accent colour | Inter if installed locally, else the system grotesk. One weight ramp. No hue anywhere. |

## 2–11. Moved

| Was | Now |
| --- | --- |
| §2 Principles | `frontend/src/design/docs/principles.md` |
| §3 Tokens | `system/tokens.md` |
| §4 Typography | `system/typography.md` |
| §5 Space, radii, layout · §10 Page anatomy | `system/space-radii-layout.md` |
| §6 Motion | `system/motion.md` |
| §7 Materials | `system/materials.md` |
| §8 Status vocabulary | `system/status.md` |
| §9 Information architecture | `system/information-architecture.md` |
| §11 Component inventory | `system/components.md` |

## 12. Page-by-page restyle checklist

Applies to every page; the shell (top bar, tokens, palette remap) is already in place, so each page is restyled
in place by its owning slice.

- [x] **App shell** — TopBar, ⌘K, theme toggle in the bar (no floating toggle), dark default.
- [x] **Hub** — deleted; `/` = reader.
- [x] **Reader `/`, `/read/*`** (851acea, 6c2890d) — drop its own wordmark and "All tools" link (the top bar has them); rail and toolbar
      sticky under the top bar (`top: var(--topbar-h)`); items as `Row`-like articles; unread = dot + weight 600.
- [x] **Post `/posts/:id`** (be501fc, 5e2dc9c) — `PageHeader` + 68ch reading column; actions as ghost buttons; summary in `<details>`.
      Replace the yellow `<mark>` highlight classes and the `bg-[rgba(253,224,71,…)]` chip with the
      `--text-highlight-bg` tint (index.css currently neutralises them globally); make the reading column
      `min-w-0` and give `<pre>` its own `overflow-x: auto` so a long code line never widens the card past the viewport.
- [x] **Sources `/settings/sources`** (1f3b2d2, df5bc3d) — `PageHeader` with one primary "Add source"; underline `Tabs`; health table
      on the `Table` primitive with `StatusGlyph`; filter chips = `FilterChip`; "Fetch now" = secondary `sm`.
- [x] **Ingestion `/ingestion`** (1f3b2d2, 83ac384) — `PageHeader`; Run cycle = primary; run report as `Notice` + `Table`; the active
      tab uses the underline `Tabs` primitive instead of `indigo/cyan` + arbitrary glow classes.
- [x] **Briefing `/briefing`** (0d36b65, 83ac384) — remove its private sidebar header/wordmark; list as `Row`s with date column.
- [x] **Stories, Inbox, Vertical briefing** (72feabb, 88d44d7) — remove "Back to hub", eyebrow pills, marketing hero copy, `app-panel`
      bubbles → `Row`/`Table`; drop the `shadow-[…rgba()]` selected-card glows (neutralised globally for now).
- [x] **Briefing** also drops the colour emoji (📊 📅) and the "I.N.S.I.G.H.T. INTELLIGENCE NETWORK" wordmark.
- [x] **Tracks `/tracks`, `/tracks/:id`** (72feabb, 87c0f3d) — `PageHeader`; track list as `Row`s with unread counts.
- [ ] Every list: worst/empty/one/huge fixtures; 375px; 200% zoom; light theme parity.

Status (2026-10-10): every page above is restyled; the commit hashes name the slices that did it.
The last item stays open. The restyled lists have worst/empty/one/huge fixtures behind the dev-only
`?data=` switch, but the 375px, 200% zoom and light-theme passes have not been recorded page by
page. Under §9 of the spec, the briefing, stories, inbox, vertical-briefing and expert
pages will be hidden when `INSIGHT_ANALYSIS=off`, so those passes matter most for feed, post,
sources and tracks.

## Lead review of the live preview (2026-10-10 00:55) — binding for page, polish and fix agents

The direction is right: black background, inverted wordmark, slash nav and type all match the reference. But the screens are about 60% there. Fix all of the following:

**Feed (/)**
1. Rows are airy and uneven. Read and star are stacked vertically at the far right, which makes every row about 100px tall. Put them in one horizontal cluster that appears on row hover/focus (always visible on touch), and aim for about 64px rows without a preview line. Titles wrap to 2 lines and never ellipsize at 1 line.
2. The list column is about 650px inside a 1400px viewport, with a large dead gutter between the rail and the list. Either centre a ~72ch list with the rail adjacent, or let the list fill the space. Follow the reference: a **date column** (`Sep 29`) on the left of each row, plus **day group headers**. Use relative "10d ago" only inside the last 24h.
3. Never show raw feed URLs as source names, in rows or in the rail. Use `display_name`, falling back to a derived name: `github.com/anthropics/claude-code/commits.atom` → `anthropics/claude-code`, `rss.arxiv.org/rss/cs.CL` → `arXiv cs.CL`, `r/x` stays as is. Add one shared `sourceLabel()` helper with tests.
4. Remove duplicated chrome:
   - the theme toggle appears in both the top bar and the page header (keep the top bar one);
   - "INSIGHT" appears as both the wordmark and the rail heading;
   - on mobile there are two hamburger menus;
   - the icon-only density toggles and the `?`/refresh icons have no labels. Use text or tooltips, and keep `?` only as the keyboard hint.
5. On mobile, three rows of controls come before any content. Collapse the filters into one row or a sheet. The meta line must not start with an orphaned "·".

**Post (/posts/:id)**
6. The H1 shows a truncated title ending in "…". Show the full title. If the stored title is truncated at ingest, derive the display title from the content's first line, and file a backend note.
7. The body renders as a monospace block that overflows horizontally. Render it as prose with wrapping at about 68ch. Use monospace only for real code blocks.
8. The notes/chat panel is the most prominent thing beside the article. Demote it: collapsed by default, or move it under the article. Reading comes first.

**Briefings (/briefing)**
9. The page opens on today's date with "0 posts". Default to the latest date that has posts.
10. The left column is a long list of verbs (Topic briefing / Weekly briefing / Weekly topics / Refresh topics / Load posts / Fetch topics / go to …). Consolidate it into one tab row (Daily · Topics · Weekly · Vertical) plus a single primary action. Navigation already lives in the top bar.

**System status**
11. The status line reads "last fetch 10d ago". On the live system, ingestion has not run since about 2026-09-30 because the ingestion container is not running. The UI must make a stale system obvious with one clear warning line (glyph + label), not quiet grey text.
