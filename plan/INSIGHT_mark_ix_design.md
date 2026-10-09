# INSIGHT Mark IX — Design language

Status: adopted 2026-10-09. Owner direction: "I don't like the Mark VIII hub at all, it's non user friendly."
Dark is **black and white only**, like news.smol.ai. Light uses the same monochrome system, inverted.
This document is the contract for every frontend slice (spec §F.6, §F.7). Implemented in
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
| Lowercase slash nav with underlines: `subscribe / issues / tags` | `feed / tracks / briefings / sources / ingestion`, underlined, current item bold with a solid underline. |
| A `Search (Cmd+K)` box on the right | A `⌘K` quick switcher, **navigation only** (search stays deferred, spec §F.2). |
| Rows: 1px grey border, ~6px radius, muted date column, bold title, chevron | `Row` primitive: date/meta column in `text-3` tabular nums, title weight 600, chevron on hover-capable pointers. |
| A grotesk sans, generous whitespace, no accent colour | Inter if installed locally, else the system grotesk. One weight ramp. No hue anywhere. |

## 2. Principles (apple-design, emil-design-eng, break-ui applied to INSIGHT)

1. **Reading first (Purpose, Simplicity).** `/` is the reader feed. The Mark VIII hub (`pages/Index.tsx`) is deleted: a page of cards that only link to other pages is navigation pretending to be content. Navigation lives in one top bar.
2. **Wayfinding on every screen.** The top bar answers *where am I* (bold, underlined nav item + page title), *where can I go* (five nav words + ⌘K), *how do I get out* (the wordmark returns to the feed). Pages drop their bespoke "Back to hub" links over time.
3. **Hierarchy by weight, size, space and contrast — never hue.** Three text tones (`text`, `text-2`, `text-3`) and two border strengths carry all hierarchy. Emphasis is weight 600, not colour.
4. **Status without colour.** Every state has a glyph (shape) + a word. The worst states are *inverted* (white block on black), so they are the loudest thing on screen without red.
5. **Response (apple §1, emil "buttons must feel responsive").** Every pressable gives `:active` feedback on press: `scale(0.97)`, 120ms, transform only. Optimistic UI where the action is reversible.
6. **Motion budget by frequency (emil).** Things done hundreds of times a day — j/k, mark read, hovers, the ⌘K switcher, tab switches — do **not** animate. Occasional surfaces (dialogs, sheets, toasts, popovers) get one short strong ease-out.
7. **Materials (apple §12).** The top bar is a translucent layer over the black page (`backdrop-filter`), content scrolls under it; no hard divider until content actually scrolls beneath. Never stack translucent on translucent.
8. **Worst-case data is an acceptance gate (break-ui).** Long titles wrap and clamp, URLs/handles middle-truncate with `title`, numbers and dates never truncate, `Intl.PluralRules`/`Intl.NumberFormat` for counts, every list has empty / one / huge fixtures behind the dev-only `?data=` switch.
9. **Accessibility signals.** `prefers-reduced-motion` → fades only; `prefers-reduced-transparency` → solid bar; `prefers-contrast: more` → borders go to `border-strong`, `text-3` goes to `text-2`. Spacing in rem so 200% zoom holds.

## 3. Tokens

All tokens are RGB channel triplets so Tailwind alpha modifiers work (`bg-surface/80`). Dark is the default
(`<html class="theme-dark dark">` is set before first paint by `index.html`).

| Token | Role | Dark (default) | Light |
| --- | --- | --- | --- |
| `--bg` | page | `#121212` | `#ffffff` |
| `--surface` | rows, cards, inputs | `#181818` | `#fafafa` |
| `--raised` | hover row, popover, dialog, selected tab | `#212121` | `#f2f2f2` |
| `--border` | 1px hairline on rows, tables, inputs | `#2b2b2b` | `#e4e4e4` |
| `--border-strong` | hover/focus borders, outline buttons | `#454545` | `#bdbdbd` |
| `--text` | primary text, titles | `#f2f2f2` | `#111111` |
| `--text-2` | secondary: meta, descriptions | `#a8a8a8` | `#555555` |
| `--text-3` | tertiary: dates, counts, hints (≥ 4.5:1 on `--bg`) | `#808080` | `#6b6b6b` |
| `--inverse` | inverted block (wordmark, primary button, failing chip) | `#f2f2f2` | `#111111` |
| `--inverse-text` | text on `--inverse` | `#121212` | `#ffffff` |
| `--scrim` | modal dimming | `0 0 0 / 0.6` | `0 0 0 / 0.35` |

Tailwind names: `bg-bg`, `bg-surface`, `bg-raised`, `border-line`, `border-line-strong`, `text-fg`, `text-fg-2`,
`text-fg-3`, `bg-inverse`, `text-inverse-fg`.

**Legacy tokens are aliases.** `--background-primary`, `--background-secondary`, `--text-normal`, `--text-muted`,
`--text-faint`, `--text-error`, `--accent-*`, `--interactive-accent*` and the shadcn HSL names now resolve to the
monochrome tokens, so every Mark VIII page turns monochrome without a rewrite. The Tailwind palette is replaced
(`frontend/tailwind.config.cjs`):

- `gray/slate/zinc/neutral/stone` map onto a smooth theme-aware grey ramp (`--n-50 … --n-950`, inverted in dark).
- every chromatic scale (`blue`, `indigo`, `emerald`, `rose`, `red`, `amber`, …) maps onto an *ink* ramp
  (`--c-*`): 50–100 are raised tints, 200–300 strong borders, 400 secondary text, 500+ the text colour. So an old
  `bg-blue-600 text-white` button becomes the inverted primary block and `text-indigo-700` becomes plain text.
- `white` is "the light surface": white in light, the row surface (`#181818`) in dark. `black` stays `#000`.
- `bg-gradient-*` utilities are not generated, and arbitrary `bg-[radial-gradient…]` values are switched off in CSS.

New code must use the semantic names above, never the ramps. The config is CommonJS (`.cjs`) on purpose: Tailwind 3
reloads its config in a running dev server through `require.cache`, which cannot evict an ES module on Node ≥ 22.

## 4. Typography

Stack: `Inter, "Inter Variable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif`.
No webfont is shipped: Inter is used where installed (it is the grotesk the reference uses), and the system
grotesk otherwise. Justification for not self-hosting: zero network cost, no FOUT, and the system faces carry their
own optical sizing (apple §15). Mono: `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace`.

| Step | Use | Size | Leading | Tracking | Weight |
| --- | --- | --- | --- | --- | --- |
| `display` | the feed's page title, empty-state headline | 1.75rem | 1.15 | −0.025em | 650 |
| `title` | page titles (`PageHeader`) | 1.375rem | 1.25 | −0.02em | 600 |
| `heading` | section headings, dialog titles | 1.0625rem | 1.35 | −0.01em | 600 |
| `body` | UI text (root 15px = 0.9375rem) | 0.9375rem | 1.55 | 0 | 400 |
| `reading` | post body, ~68ch measure | 1.125rem | 1.7 | 0 | 400 |
| `small` | meta lines, table cells | 0.8125rem | 1.45 | 0.003em | 400 |
| `micro` | column headers, kbd, chip counts | 0.75rem | 1.35 | 0.01em | 500 |

`tabular-nums` on every count, time, date and health-table number (`.num` utility, and the `Table` primitive sets it).
Lowercase is the voice of navigation and tabs (`feed / tracks`); sentence case everywhere else. No ALL-CAPS eyebrows.

## 5. Space, radii, layout

- Spacing: Tailwind's 0.25rem grid, rem only. Row padding `0.75rem 1rem`; section gap `2.5rem`; page top `2.5rem`.
- Radii: `--radius-sm` 4px (chips, kbd), `--radius` 6px (rows, inputs, buttons), `--radius-lg` 8px (dialogs, sheets).
  Tailwind `rounded-xl/2xl/3xl` are clamped to 8/8/10px so old pastel cards lose their bubble shape.
- Widths: top bar and tables `max-w-6xl` (72rem); reading column `max-w-[68ch]`; forms `max-w-2xl`.
- Top bar height `--topbar-h: 3.5rem`. Sticky children inside pages use `top: var(--topbar-h)`.
- Shadows: none on rows and cards. Overlays (dialog, sheet, popover, toast) get one neutral shadow; borders do the work.

## 6. Motion

One easing: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`. Exits are faster than entrances.

| Interaction | Duration | Property | Notes |
| --- | --- | --- | --- |
| press feedback | 120ms | transform `scale(0.97)` | every Button, Chip, Row link |
| hover / colour | 120ms | color, background-color, border-color | only under `(hover: hover) and (pointer: fine)` |
| theme switch | 200ms | background-color, color on `body` | eases the dark↔light brightness jump (apple §14) |
| popover / tooltip | 150ms | opacity + `scale(0.97→1)` from the trigger | `transform-origin` = trigger |
| dialog | 200ms in / 150ms out | opacity + `scale(0.97→1)`, centered | scrim fades 180ms |
| sheet | 260ms in / 200ms out | `translateX(100%→0)` | exits the way it came |
| toast | sonner default | transform/opacity | stacked, swipe-to-dismiss |
| j/k, mark read, ⌘K, tabs, nav | **0ms** | — | used hundreds of times a day |

Never `transition: all`, never `scale(0)`, never `ease-in`. Reduced motion: dialogs/sheets/popovers become a 150ms
opacity fade; press scale is removed.

## 7. Materials

- **Top bar**: `rgb(var(--bg) / 0.78)` + `backdrop-filter: blur(16px) saturate(140%)`; a hairline border appears only
  once the page is scrolled (`data-scrolled`). Reduced transparency → solid `--bg`.
- **Sticky sub-toolbars** (reader toolbar, health table header) use `.material` with the same recipe, sitting *below*
  the top bar (`top: var(--topbar-h)`), never over it.
- **Overlays**: solid `--raised` (no glass), 1px `--border-strong`, scrim `--scrim`.

## 8. Status vocabulary (no colour)

Glyphs are inline SVG (font-independent) at 0.625rem, `aria-hidden`; the word is always present (visible or `sr-only`).
Rendered by `<StatusGlyph status="…" />`.

| Status | Glyph | Word | Treatment |
| --- | --- | --- | --- |
| `ok` | ● filled circle | ok | `text-2` |
| `due` | ◐ half circle | due | `text`, weight 600 |
| `scheduled` | ○ ring | scheduled | `text-3` |
| `backoff` | ◌ dashed ring | backoff | `text`, dashed 1px border chip |
| `failing` | × in a square | failing | **inverted chip** (`--inverse` bg, `--inverse-text`), weight 600 |
| `unavailable` | ⊘ slashed ring | unavailable | `text-2`, 1px border chip |
| `disabled` | – dash | disabled | `text-3`, line-through off, italic off |
| `unread` | ● small dot | unread | `text`; titles also go weight 600 |
| `read` | ○ small ring | read | `text-3`; title weight 400, `text-2` |
| `starred` | ★ filled star | starred | `text` |
| `running` | ◐ (static) + "running…" | running | `text`; no spinner loop faster than needed |

Destructive actions: `Button variant="danger"` is an inverted block whose label starts with "×"-free text but which
always sits behind a `ConfirmDialog`; errors use `Notice tone="error"` (inverted glyph block + label).

## 9. Information architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│ [INSIGHT]                     feed / tracks / briefings / sources / ingestion  [⌘K] ☾ │
└────────────────────────────────────────────────────────────────────────────┘
```

| Nav word | Route | Active on |
| --- | --- | --- |
| feed | `/` | `/`, `/read/*`, `/posts/*` |
| tracks | `/tracks` (= Experts/Tracks page) | `/tracks*`, `/experts` |
| briefings | `/briefing` | `/briefing*`, `/stories`, `/inbox` |
| sources | `/settings/sources` | `/settings/*` |
| ingestion | `/ingestion` | `/ingestion*` |

- `/hub` and the old `/` hub are gone (`/hub` redirects to `/`).
- **⌘K / Ctrl+K quick switcher**: a centered dialog listing every destination (feed, starred, unread, tracks,
  briefing, vertical briefing, stories, inbox, sources, source health, ingestion, toggle theme). Type to filter,
  ↑/↓ to move, Enter to go. No animation. It does not search posts.
- Below `sm` (640px) the nav words collapse into a `menu` button that opens the same switcher.

## 10. Page anatomy

```
PageHeader   title (title step) · optional meta line in text-2 ("90 sources · as of just now")
             actions right-aligned (one primary, the rest secondary/ghost)
Tabs         lowercase underline tabs under the header when the page has views
Content      reading: max-w-[68ch]; lists: max-w-3xl; tables/ops: max-w-6xl
```

One primary (inverted) button per view. Page padding: `px-4 sm:px-6`, top `pt-8 sm:pt-10`, bottom `pb-24`.

## 11. Component inventory (`src/components/ui`)

| Component | Do | Don't |
| --- | --- | --- |
| `Button` (`primary` inverted, `secondary` outline, `ghost`, `danger` inverted+border; `sm`/`md`/`icon`) | one primary per view; 2.25rem tall (`md`), 44px hit area on touch via `icon` size | coloured fills, gradients, icon-only without `aria-label` |
| `TextLink` | underlined, `text` colour, underline thickens on hover | blue links |
| `Chip` / `FilterChip` | `outline` default, `solid` = inverted for selected/strong; counts in `tabular-nums` | pastel backgrounds |
| `StatusGlyph` | glyph + word (§8) | colour-only dots |
| `Tabs` | Radix tabs, lowercase underline; no animation | pill tabs with shadows |
| `Table` (`Table`, `THead`, `TBody`, `Tr`, `Th`, `Td`) | 1px row hairlines, `small` text, `tabular-nums`, sticky header uses `.material` | zebra stripes, coloured headers |
| `Row` | smol-style bordered row: meta column, bold title, chevron | cards with icons in tinted squares |
| `Input`, `Textarea`, `Select` (native) | `surface` bg, 1px `border`, focus = `border-strong` + 2px outline | glow rings |
| `Dialog`, `Sheet` | Radix; dialog centered, sheet from the right; scrim | glass on glass |
| `Toaster` | sonner, monochrome via CSS vars; outcome + link to the job | rich (coloured) toasts |
| `Skeleton` | `raised` blocks, pulse only when motion is allowed | shimmering gradients |
| `Kbd` | `micro` mono in a 1px box | — |
| `PageHeader` | title + meta + actions | eyebrow pills ("INSIGHT WORKSPACE") |
| `states/*` | `LoadingState`, `EmptyState`, `ErrorState`, `Notice` use the primitives above | — |

## 12. Page-by-page restyle checklist

Applies to every page; the shell (top bar, tokens, palette remap) is already in place, so each page is restyled
in place by its owning slice.

- [x] **App shell** — TopBar, ⌘K, theme toggle in the bar (no floating toggle), dark default.
- [x] **Hub** — deleted; `/` = reader.
- [ ] **Reader `/`, `/read/*`** — drop its own wordmark and "All tools" link (the top bar has them); rail and toolbar
      sticky under the top bar (`top: var(--topbar-h)`); items as `Row`-like articles; unread = dot + weight 600.
- [ ] **Post `/posts/:id`** — `PageHeader` + 68ch reading column; actions as ghost buttons; summary in `<details>`.
      Replace the yellow `<mark>` highlight classes and the `bg-[rgba(253,224,71,…)]` chip with the
      `--text-highlight-bg` tint (index.css currently neutralises them globally); make the reading column
      `min-w-0` and give `<pre>` its own `overflow-x: auto` so a long code line never widens the card past the viewport.
- [ ] **Sources `/settings/sources`** — `PageHeader` with one primary "Add source"; underline `Tabs`; health table
      on the `Table` primitive with `StatusGlyph`; filter chips = `FilterChip`; "Fetch now" = secondary `sm`.
- [ ] **Ingestion `/ingestion`** — `PageHeader`; Run cycle = primary; run report as `Notice` + `Table`; the active
      tab uses the underline `Tabs` primitive instead of `indigo/cyan` + arbitrary glow classes.
- [ ] **Briefing `/briefing`** — remove its private sidebar header/wordmark; list as `Row`s with date column.
- [ ] **Stories, Inbox, Vertical briefing** — remove "Back to hub", eyebrow pills, marketing hero copy, `app-panel`
      bubbles → `Row`/`Table`; drop the `shadow-[…rgba()]` selected-card glows (neutralised globally for now).
- [ ] **Briefing** also drops the colour emoji (📊 📅) and the "I.N.S.I.G.H.T. INTELLIGENCE NETWORK" wordmark.
- [ ] **Tracks `/tracks`, `/tracks/:id`** — `PageHeader`; track list as `Row`s with unread counts.
- [ ] Every list: worst/empty/one/huge fixtures; 375px; 200% zoom; light theme parity.

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
