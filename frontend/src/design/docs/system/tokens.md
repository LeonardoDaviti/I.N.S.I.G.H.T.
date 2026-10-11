```meta
kind: system
```

# Tokens

Implements P2 and P3. Source: `src/index.css` (values) and `tailwind.config.cjs` (names). The studio renders these live from the CSS custom properties (S2), so this table is the contract, not a copy to keep in sync by hand.

All tokens are RGB channel triplets so Tailwind alpha modifiers work (`bg-surface/80`). Dark is the default: `index.html` sets `<html class="theme-dark dark">` before first paint.

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

Tailwind names: `bg-bg`, `bg-surface`, `bg-raised`, `border-line`, `border-line-strong`, `text-fg`, `text-fg-2`, `text-fg-3`, `bg-inverse`, `text-inverse-fg`. New code uses these semantic names, never the ramps below.

**High contrast.** Under `prefers-contrast: more`, `--border` becomes `--border-strong` and `--text-3` becomes `--text-2`.

## Legacy aliases

`--background-primary`, `--background-secondary`, `--text-normal`, `--text-muted`, `--text-faint`, `--text-error`, `--accent-*`, `--interactive-accent*` and the shadcn HSL names resolve to the monochrome tokens, so every Mark VIII page is monochrome without a rewrite. The Tailwind palette is replaced:

- `gray/slate/zinc/neutral/stone` map onto a theme-aware grey ramp (`--n-50 … --n-950`, inverted in dark).
- Every chromatic scale (`blue`, `indigo`, `emerald`, `rose`, `red`, `amber`, …) maps onto an *ink* ramp (`--c-*`): 50–100 are raised tints, 200–300 strong borders, 400 secondary text, 500+ the text colour. An old `bg-blue-600 text-white` button becomes the inverted primary block.
- `white` is "the light surface": white in light, `#181818` in dark. `black` stays `#000`.
- `bg-gradient-*` utilities are not generated, and arbitrary `bg-[radial-gradient…]` values are switched off in CSS.

The config is CommonJS (`.cjs`) on purpose: Tailwind 3 reloads its config in a running dev server through `require.cache`, which cannot evict an ES module on Node ≥ 22.
