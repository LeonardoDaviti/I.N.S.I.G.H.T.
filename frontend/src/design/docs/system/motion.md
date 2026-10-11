```meta
kind: system
```

# Motion

Implements P12. Source: `src/index.css` (motion section), `components/states/press.ts`.

**Budget by frequency.** What is done hundreds of times a day (j/k, mark read, hovers, ⌘K, tab switches) does **not** animate. Occasional surfaces (dialogs, sheets, toasts, popovers) get one short, strong ease-out.

**Response.** Every pressable answers a press with `scale(0.97)`, 120ms, transform only. Optimistic UI where the action is reversible (read, star).

One easing: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`. Exits are faster than entrances.

| Interaction | Duration | Property | Notes |
| --- | --- | --- | --- |
| press feedback | 120ms | transform `scale(0.97)` | every Button, Chip, Row link; not on a key press |
| hover / colour | 120ms | color, background-color, border-color | only under `(hover: hover) and (pointer: fine)` |
| theme switch | 200ms | background-color, color on `body` | eases the dark↔light brightness jump |
| popover / tooltip | 150ms | opacity + `scale(0.97→1)` from the trigger | `transform-origin` = trigger |
| dialog | 200ms in / 150ms out | opacity + `scale(0.97→1)`, centred | scrim fades 180ms |
| sheet | 260ms in / 200ms out | `translateX(100%→0)` | exits the way it came |
| toast | sonner default | transform/opacity | stacked, swipe to dismiss |
| j/k, mark read, ⌘K, tabs, nav | **0ms** | — | used hundreds of times a day |

Never `transition: all`, never `scale(0)`, never `ease-in`.

**Reduced motion** (`prefers-reduced-motion`): dialogs, sheets and popovers become a 150ms opacity fade; press scale is removed; skeletons stop pulsing.
