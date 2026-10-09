# Worst-case catalog

> Reconstructed for INSIGHT: the original break-ui skill references a CATALOG.md that wasn't supplied. Rows are grouped by category; pick the ones that apply to the surface under test. INSIGHT-specific examples are drawn from real source kinds (Telegram, Reddit, YouTube, RSS, arXiv, Nitter).

## Text

| Case | Example | Why it breaks |
| --- | --- | --- |
| Long but real title | `Claude Code 2.4 release notes: hooks, background agents, worktree isolation, and the new permission model explained` | Overflows single-line rows; wraps badges |
| arXiv title | `Scaling Laws for Sparse Mixture-of-Experts Language Models Under Compute-Optimal Token-to-Parameter Ratios: An Empirical Study` | Very long, no natural break near the end |
| One-word / one-letter title | `Q`, `—`, `.` | Orphaned separators, collapsed row heights |
| Missing title | `""` / `null` (Telegram posts often have no title) | Empty heading line, "undefined" |
| Unbreakable token | `https://github.com/anthropics/claude-code/releases/tag/v2.4.0-beta.17+build.20261009` | Runs past container edge |
| Long source name | `r/MachineLearning — Discussion & Research (Daily Megathread Archive)` | Pushes trailing actions off-row |
| Handle-only source | `@karpathy`, `t.me/s/ai_newz` | Initials/avatars from non-word characters |
| Non-Latin | `Нейросети и машинное обучение`, `人工智能前沿`, `ภาษาไทย`, `Tiếng Việt có dấu` | Clipped diacritics; width assumptions |
| RTL | `الذكاء الاصطناعي` | Mirrored layout, punctuation at wrong end |
| Emoji-first | `🚀 Launch day` , `👨‍👩‍👧 family` (ZWJ cluster) | Broken initials, grapheme splitting |
| Raw markup in content | `<b>bold</b>`, `&amp;`, `**markdown**`, `` `code` `` | Double-escaping or unsafe HTML |
| Very long body | 40k-char Telegram post / transcript | Layout, scroll performance, clamp behaviour |
| Whitespace-only / leading newlines | `"\n\n   text"` | Blank first line, wrong preview |

## Identifiers

| Case | Example | Why it breaks |
| --- | --- | --- |
| UUIDs | `3f2b9c1e-...` shown in UI | Monospace width, no wrap |
| Long URLs with query strings | `...?utm_source=...&utm_medium=...` | Middle-truncation needed |
| Duplicate display names | two sources both named `Simon Willison` | Ambiguity; need secondary label |

## Numbers

| Case | Example | Why it breaks |
| --- | --- | --- |
| Zero | `0 posts`, `0 unread` | Pluralization, empty states |
| One | `1 post` | "1 posts" |
| Large | `12,847 unread`, `1,284 sources` | Badge overflow, missing separators |
| Huge | `2,147,483,647` | Layout, formatting |
| Null / NaN | `null`, `undefined`, `NaN` remaining posts | Raw rendering |
| Durations | `0s`, `59s`, `21 days`, `3 years` estimate | Formatting, unit choice |
| Negative | backlog `-3` (stale counts) | Should never render negative |

## Collections

| Case | Example | Why it breaks |
| --- | --- | --- |
| Empty | no posts in feed, no sources in track | Missing empty state |
| One | single source in a track | Layout built for many |
| Many | 223 sources, 1,000+ feed items | Performance, virtualization |
| Skewed | arXiv = 47% of items | Grouping, by-source view |
| Many tags/badges | 12 topics on a post | Wrapping chips |

## Time

| Case | Example | Why it breaks |
| --- | --- | --- |
| Just now | published 2s ago | "0 minutes ago" |
| Future | `published_at` in the future (bad feed clocks) | "in 3 hours" or negative |
| Very old | 2009 blog post | Relative time absurd ("16 years ago") — show date |
| Missing | `published_at = null` | Sort order, "Invalid Date" |
| Timezone boundary | 23:59 UTC vs local date | Wrong day grouping |

## Media

| Case | Example | Why it breaks |
| --- | --- | --- |
| Broken image | 404 thumbnail / avatar | Broken-image icon |
| Extreme aspect ratio | 10:1 banner, 1:4 portrait | Stretched or cropped badly |
| No media | text-only post | Reserved empty box |
| Slow media | 5MB image on slow link | Layout shift |

## States

| Case | Example | Why it breaks |
| --- | --- | --- |
| Loading | slow API (3s+) | Skeleton vs spinner, layout shift |
| Error | `success:false` with long error message | Error box overflow |
| Partial | half the sources failed in a run report | Mixed success/failure display |
| Disabled / unavailable | source kind unavailable (yt-dlp off, no Telegram session) | Unexplained greyed-out controls |
| Backoff | source in backoff until a timestamp, 9 consecutive failures | Long reason strings |
| Concurrent | run already in progress (503/409) | Double-submit, stale buttons |

## Environment

| Case | Example | Why it breaks |
| --- | --- | --- |
| Narrow | 320px width | Overflow, hidden actions |
| Wide | 2560px | Unbounded line length (reading measure) |
| Zoom 200% | root font size raised | Fixed-px boxes |
| Dark mode | `prefers-color-scheme: dark` | Hardcoded colors |
| Reduced motion | `prefers-reduced-motion: reduce` | Unwanted slides |
| Keyboard only | Tab / j / k / ? | Focus rings, traps |
| Touch | no hover | Hover-only affordances |
