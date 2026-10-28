# 0033 — Continuous reading: one calm column of separate articles

Status: **built** 2026-10-28, not yet deployed. UX, design pass on [0014](0014-continuous-reading.md).

## What the owner saw
On v9.1, scrolling past one post into the next showed a divider carrying "source / title [...]", then the next post's byline "turboproject / settings / rss / Oct 21, 2026, 7:08 PM", then its title as an h1. "Why do I see the title two times? Just the separator line should remain, remove the top titling, and also remove the source type."

## Already fixed on main
- The divider is a plain `border-strong` rule (f942f98).
- The byline no longer shows the platform (4277ace, issue 0027).

## What changed (and why)
Looked at for real on the preview data: a Russian Telegram channel (@seeallochnaya), simonwillison.net and a three-video YouTube source, at 1400 px and 390 px, dark and light.

- **`settings` only on the stream's first post** (decision 026, P6, P8). Every join repeated "source / settings / date"; in a source's stream that is the same link on every post. The first byline keeps it (one click to manage the source); a post that follows reads source / date. The source name still opens that source's feed, and the reader's header links into Sources.
- **The byline date drops this year** (decision 027, P6). "Sep 22, 2026, 10:19 PM" beside three actions wrapped on a phone, leaving a second line that started with "/". Now it reads "Sep 22, 10:19 PM" (another year keeps its year), with the full date and time in the `<time>` tooltip. A joined post's byline now fits on one line at 390 px.

## Looked at and kept
- **The join:** 4 rem above the rule, 2.5 rem below, then byline and title. The rule belongs to the post below, and the byline plus the title already say "a new post starts here". No change.
- **The action row on every post:** kept at full strength, since star and copy act on that post, and a post that comes first in one stream follows in another.
- **The sticky navigation:** acts on the post at the midline (Previous becomes enabled once the second post is current). It names no post, so the title isn't shown a second time.
- **The end:** a weaker `border-line` rule, "You're all caught up" / "You've reached the end", the large navigation. It reads as the end, distinct from a join.
- **Long and Cyrillic titles:** wrap with `text-pretty` and `dir="auto"`; fine at both widths.

## Noted, not changed here
- Telegram posts from the tg.i-c-a.su bridge arrive with a title cut with "[...]", so the H1 repeats the first line of the body below it. The title is the backend's `display_title` (it recognises "…", not "[...]"); a follow-up for the title rule or issue 0032.
- A body image that never loads leaves an empty gap above the text (reading fidelity, issue 0032).

## Screenshots (not committed, decision 018)
`~/.cache/insight-0033/shots/before/` and `.../after/`: `tg-{desk,phone}-{dark,light}-{0top,1join,2join}.png`, `sw-*` the same, `yt-{desk,phone}-{join,end}.png`. Compare `tg-phone-dark-1join.png` before and after.

## Testing
- `PostDetailPage.test.tsx`: only the first post's byline has `settings`; the next has source, date and its own actions.
- `lib/dates.test.ts`: `postBylineTime` omits this year, keeps another year.
