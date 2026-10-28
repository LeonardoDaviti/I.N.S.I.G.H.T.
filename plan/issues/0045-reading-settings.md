# 0045 — Reading settings: font, size and width

Status: **planned** for v9.5 (owner, 2026-10-28).

## Decided
- **Three settings, nothing more:**
  - **font:** serif or sans, using the fonts INSIGHT already ships (no new font files unless one is missing and small; state the bytes);
  - **text size:** about 5 steps around today's size;
  - **column width:** narrow, standard (today), wide.
- **Not a density setting.** Line height, spacing and the calm continuous column stay as decided in 0033/0034 ("I don't want to read compactly"). Size and width scale the column; they never pack it tighter.
- **Where:** one small "Aa" control in the reader's toolbar, opening a popover with the three settings and a live preview on the text behind it. Also listed in Settings. Reachable by keyboard.
- **Per device**, in local storage, since phone and desktop want different sizes. No backend.
- **Applies to** the continuous reader and the post page, including 0042's tables, figures and captions, and code blocks. The interface around the text (rail, toolbar) is unchanged.
- **Design docs:** say where the setting lives and what it may change (`frontend/src/design/docs/`). A numbered decision is needed if it changes a recorded rule, e.g. the single density (0034).

## Done when
- Frontend tests cover each setting applied and persisted, defaults equal today's look exactly, keyboard use, and the popover.
- Typecheck, test, lint and build pass, with the bundle change stated (reader's initial JS budget 1%; prefer lazy-loading the popover).
