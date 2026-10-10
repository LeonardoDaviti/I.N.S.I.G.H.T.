```meta
kind: system
```

# Status vocabulary

Implements P2 and P11. Rendered by `<StatusGlyph status="…" />` (`components/ui/StatusGlyph.tsx`).

Every state is a shape plus a word, never colour alone. Glyphs are inline SVG (font-independent) at 0.625rem, `aria-hidden`; the word is always present (visible or `sr-only`). The worst states are *inverted* (light block on black), so they are the loudest thing on screen without red.

| Status | Glyph | Word | Treatment |
| --- | --- | --- | --- |
| `ok` | ● filled circle | ok | `text-2` |
| `due` | ◐ half circle | due | `text`, weight 600 |
| `scheduled` | ○ ring | scheduled | `text-3` |
| `backoff` | ◌ dashed ring | backoff | `text`, dashed 1px border chip |
| `failing` | × in a square | failing | **inverted chip** (`--inverse` bg, `--inverse-text`), weight 600 |
| `unavailable` | ⊘ slashed ring | unavailable | `text-2`, 1px border chip |
| `disabled` | – dash | disabled | `text-3` |
| `unread` | ● small dot | unread | `text`; titles also go weight 600 |
| `read` | ○ small ring | read | `text-3`; title weight 400, `text-2` |
| `starred` | ★ filled star | starred | `text` |
| `running` | ◐ (static) + "running…" | running | `text`; no spinner loop faster than needed |

Connections reuse the glyphs with their own words: `working`, `set · not tested`, `failing`, `incomplete`, `sign in needed`, `not set`, `not needed` (`components/connections/connectionStatus.ts`).

- **Destructive actions:** `Button variant="danger"` is an inverted block and always sits behind a `ConfirmDialog` that says what goes with it.
- **Errors:** `Notice tone="error"` and `ErrorState` (inverted glyph block + the word). Warnings use a dashed border.
- **A stopped system** is one clear warning line (`IngestionStatusNotice`, glyph + label), not quiet grey text.
