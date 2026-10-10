```meta
kind: system
```

# Space, radii, layout

Implements P3 and P4. Source: `src/index.css`, `tailwind.config.cjs`, `components/ui/PageHeader.tsx`.

- **Spacing:** Tailwind's 0.25rem grid, rem only, so 200% zoom holds. Row padding `0.75rem 1rem`; section gap `2.5rem`; page top `2.5rem`.
- **Radii:** `--radius-sm` 4px (chips, kbd), `--radius` 6px (rows, inputs, buttons), `--radius-lg` 8px (dialogs, sheets). Tailwind `rounded-xl/2xl/3xl` are clamped to 8/8/10px.
- **Widths:** top bar and tables `max-w-6xl` (72rem); reading column `max-w-[68ch]`; forms `max-w-2xl`. `Page width="reading" | "list" | "wide"` picks one.
- **Top bar:** height `--topbar-h: 3.5rem`. Sticky children inside pages use `top: var(--topbar-h)`.
- **Shadows:** none on rows and cards. Overlays (dialog, sheet, popover, toast) get one neutral shadow; borders do the work.
- **Touch:** every control is at least 44px on a coarse pointer (`coarse:` variant), 32–36px with a mouse.

## Page anatomy

```
PageHeader   title (title step) · optional meta line in text-2
             actions right-aligned (one primary, the rest secondary/ghost)
Tabs         lowercase underline tabs under the header when the page has views
Content      reading: max-w-[68ch]; lists: max-w-3xl; tables/ops: max-w-6xl
```

One primary (inverted) button per view. Page padding: `px-4 sm:px-6`, top `pt-8 sm:pt-10`, bottom `pb-24`.
