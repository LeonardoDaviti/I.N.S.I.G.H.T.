```meta
kind: system
```

# Materials

Implements P2 and P12. Source: `src/index.css` (`.material`, `.reader-material`).

- **Top bar:** `rgb(var(--bg) / 0.78)` + `backdrop-filter: blur(16px) saturate(140%)`. Content scrolls under it; a hairline border appears only once content is beneath it (`data-scrolled`), never before.
- **Sticky sub-toolbars** (reader toolbar, sources group headers, table headers) use the same recipe, sitting *below* the top bar (`top: var(--topbar-h)`), never over it.
- **Overlays:** solid `--raised` (no glass), 1px `--border-strong`, scrim `--scrim`. Never stack translucent on translucent.
- **Reduced transparency** (`prefers-reduced-transparency`): every material becomes solid `--bg`.
