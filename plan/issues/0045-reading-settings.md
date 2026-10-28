# 0045 — Reading settings: font, size and width

Status: **built, not deployed** (2026-10-28, branch `issue-0045-reading-settings`). Planned for v9.5 (owner, 2026-10-28).

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

## Built
- **Three settings, one module** (`frontend/src/lib/readingSettings.ts`): font `sans / serif`, size
  `90% / 95% / 100% / 110% / 125%` of today's reading step (1.0625rem on a phone, 1.125rem from sm
  up), width `narrow / standard / wide` (column 36rem / 42rem / 52rem, measure 58ch / 68ch / 84ch).
  `readingStyle` turns them into CSS variables (`--reading-font`, `--reading-scale`,
  `--reading-column`, `--reading-measure`) and sets **none for the defaults**, so each use falls
  back to today's value (42rem, 68ch, 1.0625rem / 1.125rem, the inherited sans): the default look
  is exactly the old one, not a recomputation of it.
- **Fonts:** INSIGHT ships no webfont (system/typography.md), so the serif is a system stack
  (`ui-serif, "Iowan Old Style", Charter, …, Georgia, "Noto Serif", "Times New Roman", serif`):
  **0 bytes**, nothing downloaded, no flash.
- **Not a density:** the text keeps `leading-[1.7]`, and the body's spacing, tables, figures,
  captions and code are all in em (`MarkdownRenderer`), so they grow and shrink with the size;
  nothing gets tighter. Width moves the column (the title, the text and the navigation band's
  grid) and the measure together.
- **Where it applies:** the post page and the continuous stream, through one `ReadingFrame`
  (`display: contents`) around the page, the loading skeleton too. The text block uses
  `READING_TEXT_CLASS`; the title takes the font. The byline, actions, navigation band, rail and
  top bar keep their type.
- **Aa** (`components/post/ReadingSettingsButton.tsx`) at the right of the post's sticky
  navigation band: a non-modal popover (`role="dialog"`, so the post's single keys stay off while
  in it) over the text, which is the live preview. Enter or click opens it and focuses it; Tab
  reaches the three slash choices (`SlashChoice`), Enter or Space picks; Escape closes back to Aa
  without the post's own Escape (back) firing; a click outside or focus leaving closes it. The
  panel (`ReadingSettingsPanel.tsx`) is lazy-loaded on first open.
- **Under 360px** the band also holds Aa, so there Previous and Next show only their arrows (the
  words stay their accessible names); the band stays one line (post.md). The row after the post is
  unchanged.
- **"Settings":** INSIGHT has no Settings page (`/settings/sources` is Sources), so the settings
  are listed in ⌘K, beside the theme: "Reading settings: font, size, width" (group settings) opens
  a dialog with the same panel over a sample paragraph set as a post (`ReadingSettingsDialog.tsx`,
  lazy, from `AppShell`). Reachable from the feed too.
- **Per device:** `insight.reader.font`, `.size`, `.width` in local storage through the reader's
  stored-choice store (`useReadingSettings`), so the popover, the dialog and the page change
  together, and another tab follows; an unknown stored value reads as the default. No backend.
- **Docs:** decision **031** (it widens P4's single 68ch measure to a per-device choice with 68ch
  the default; the leading, spacing and one density of 026 are unchanged), `pages/post.md` (Aa,
  the popover, what the settings may change, keys), `pages/shell.md` (the ⌘K entry),
  `system/typography.md` (the variables and the serif stack). principles.md unchanged.
- **Bundle:** the reader's initial JS 472,205 -> 473,367 bytes (+1,162, +0.25%; budget 1%): the
  ⌘K entry and the dialog's lazy import. The panel (903 B), the dialog (891 B) and the settings
  hook and module (1,573 B) are their own chunks.
- **Tests:** `src/lib/readingSettings.test.ts` (no variable by default, each setting's variables,
  the five steps); `src/pages/PostDetailPage.reading.test.tsx` (7: defaults equal today's classes
  with no variable set, the popover and today's choices checked, each setting applied and
  persisted and back to nothing, a stored choice applied on open and an unknown one ignored,
  tables / figures / captions / code inside the scaled text and the title taking the font, the
  keyboard path, a click outside); `layout.test.tsx` (the ⌘K entry and its dialog).
- **Not done:** no screenshot pass (`design:shots` needs Playwright, not run here); the 360px
  breakpoint for the band's arrows is estimated from the buttons' sizes, not a rendered check.

