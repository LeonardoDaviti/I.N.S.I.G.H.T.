```meta
kind: system
```

# Typography

Implements P3 and P4. Source: `src/index.css`, `components/ui/MarkdownRenderer.tsx`.

Stack: `Inter, "Inter Variable", ui-sans-serif, system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif`. No webfont is shipped: Inter is used where installed (the grotesk the reference uses), else the system grotesk. Zero network cost, no FOUT, and system faces carry their own optical sizing. Mono: `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace`, for real code only.

| Step | Use | Size | Leading | Tracking | Weight |
| --- | --- | --- | --- | --- | --- |
| `display` | post title, empty-state headline | 1.75rem | 1.15 | −0.025em | 650 |
| `title` | page titles (`PageHeader`) | 1.375rem | 1.25 | −0.02em | 600 |
| `heading` | section headings, dialog titles | 1.0625rem | 1.35 | −0.01em | 600 |
| `body` | UI text (root 15px = 0.9375rem) | 0.9375rem | 1.55 | 0 | 400 |
| `reading` | post body, ~68ch measure | 1.125rem | 1.7 | 0 | 400 |
| `small` | meta lines, table cells | 0.8125rem | 1.45 | 0.003em | 400 |
| `micro` | column headers, kbd, chip counts | 0.75rem | 1.35 | 0.01em | 500 |

- `tabular-nums` on every count, time, date and table number.
- Lowercase is the voice of navigation and tabs (`feed / sources`); sentence case everywhere else. No ALL-CAPS eyebrows.
- Headings balance their lines (`text-wrap: balance`) unless they opt out with `text-pretty`, as the post title does. Whether the post title keeps `pretty` is the seed prototype (D6).
- Text that may be in any script carries `dir="auto"` (feed titles, post title, excerpts).
- `MarkdownRenderer` styles `h1`–`h6` on one scale (size, weight and spacing, never colour; `h6` is muted), so no heading level renders like body text.
- A figure's caption and a table's caption sit under what they describe, at 0.875em in `text-2`, never italic or coloured.
- **Reading settings** (decision 031, `lib/readingSettings.ts`) change the post text only, through CSS variables on the post page, none set by default: `--reading-font` (serif: `ui-serif, "Iowan Old Style", Charter, …, Georgia, serif`, system faces, 0 bytes, so still no webfont), `--reading-scale` (0.9, 0.95, 1, 1.1, 1.25 times the `reading` step) and `--reading-column` / `--reading-measure` (36rem / 58ch, 42rem / 68ch, 52rem / 84ch). The leading stays 1.7 at every size.
