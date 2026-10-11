```meta
kind: system
```

# Component inventory

Implements P2, P3, P5 and P11. Source: `src/components/ui`, `src/components/states`. Each primitive gets a specimen in the studio (S2).

| Component | Do | Don't |
| --- | --- | --- |
| `Button` (`primary` inverted, `secondary` outline, `ghost`, `danger` inverted+border; `sm`/`md`/`icon`) | one primary per view; 2.25rem tall (`md`), 44px hit area on touch via `icon` | coloured fills, gradients, icon-only without `aria-label` |
| `TextLink` | underlined, `text` colour, underline thickens on hover | blue links |
| `Chip` / `FilterChip` | `outline` default, `solid` = inverted for selected/strong; counts in `tabular-nums` | pastel backgrounds |
| `StatusGlyph` | glyph + word (`system/status.md`) | colour-only dots |
| `Tabs` | Radix tabs, lowercase underline; no animation | pill tabs with shadows |
| `Input`, `Textarea`, `Select` (native) | `surface` bg, 1px `border`, focus = `border-strong` + 2px outline | glow rings |
| `Switch` | inverted pill when on, hairline when off | a coloured track |
| `Dialog`, `Sheet` | Radix; dialog centred, sheet from the right; scrim | glass on glass |
| `Toaster` | sonner, monochrome via CSS vars; outcome + link to the job | rich (coloured) toasts |
| `Skeleton` | `raised` blocks, pulse only when motion is allowed | shimmering gradients |
| `Kbd` | `micro` mono in a 1px box | — |
| `PageHeader` | title + meta + actions | eyebrow pills ("INSIGHT WORKSPACE") |
| `MarkdownRenderer` | prose in em units, GFM tables, monospace only for code | raw HTML styling |
| `states/*` | `LoadingState`, `EmptyState`, `ErrorState`, `Notice` built on the primitives above | — |

Every focusable element shows the same ring: a 2px outline in the text colour (`FOCUS_RING`). Press feedback is `PRESS_FEEDBACK` (`system/motion.md`).
