```meta
kind: page
routes: /posts/:postId
states: article, media, long-title, headings, missing-title, loading, error
```

# Post

Code: `pages/PostDetailPage.tsx`, `components/post/*` (`PostActions`, `PostImages`), `components/ui/MarkdownRenderer.tsx`, `lib/postTitle.ts`.

## Purpose

Read one post, whole, in one centred column with nothing beside it (P4). It is the content and three actions; nothing else.

## Entry & URL

- `/posts/:postId`, opened from a feed row (title link, `o`/Enter) or a link elsewhere.
- `?ctx=` carries the feed it came from (scope, filter, page cursor), so prev/next and "Back" survive a reload. Without it there is no prev/next and the way out reads "Back to feed".
- Dev-only `?data=worst|empty|missing|slow` swaps in fixtures.
- The post loads through `usePost`, so a post the feed prefetched opens from cache with no skeleton. Opening a post marks it read; the feed's cached rows and counts follow.

## Anatomy

- **Post navigation** (ghost buttons, `sm`): Back / Back to feed; with a context, Previous and Next.
- **Header:** one line of byline in `small` `text-2`: the source name (a quiet link to `/settings/sources?source=<id>`, P8), ` / platform`, ` / date` (each "/ part" wraps as one). At its right the actions, icon-only with tooltips (P5): ↗ open original (when there is a URL), ☆ star, ⧉ copy text (✓ "Copied" for a moment).
- **Title:** `h1` at the display step (1.75rem, 2rem from sm), weight 650, `text-pretty`, `dir="auto"`. A stored title cut with "…" shows the text's whole first line instead (`displayPostTitle`).
- **Hero media:** the first image as a figure, or an embedded video in a reserved 16:9 frame.
- **Body:** the content as wrapped prose through `MarkdownRenderer` at the reading measure (~68ch); monospace only for real code blocks, which scroll on their own.
- **More images** after the body.
- **YouTube posts:** the player, a line of duration / views / likes / transcript source, a "Watch progress" card (progress bar, position slider, Save progress, Mark complete), then the transcript in collapsed blocks with "Set progress here" and "Open at m:ss".
- **Reddit posts:** a "Discussion" section with the stored comments.
- Column: `grid-cols-[minmax(0,42rem)]`, centred, page `max-w-6xl`, `pb-24`.

## States

- **article:** a text post: byline, title, prose.
- **media:** a hero image, more images after the body, and a video (YouTube embed or watch mode).
- **long-title:** a title of several lines wraps (never truncates) and balances with `pretty`.
- **headings:** a body using h1–h6, lists, quotes, tables and code, to check the prose scale.
- **missing-title:** a Telegram or commit post with no real title: the H1 is the text's first line.
- **loading:** a skeleton in the same frame and column as the loaded page, so nothing jumps on arrival.
- **error:** "Post not found" with the error message and "Back to the feed". An action that fails (star, copy) shows an error `Notice` with Dismiss above the body.

## Interactions & keys

- `j`/`k` next / previous post in the feed (with a context), `u`/Esc back, `m` toggle read, `s` star, `?` the shortcut table.
- Prev/next replace the history entry, so Back leaves the post rather than walking every post read.
- Star is optimistic and rolls back on failure. Copy puts the stored text (or the HTML's text) on the clipboard.

## Worst cases

- Unbroken URLs and long words wrap (`break-words`, `[overflow-wrap:anywhere]`); the column is `min-w-0`, and `<pre>` scrolls inside itself, so nothing widens the page past the viewport.
- The source name middle-truncates at 40 chars, full name in `title`.
- RTL and mixed-script titles via `dir="auto"`.
- A post with no content: an empty body, still readable header. A video with no transcript says so.

## A11y & motion

- Header actions are a labelled group; each icon has an `aria-label` and a tooltip; star is `aria-pressed`. Key presses do not trigger the press scale (only pointer presses do).
- The body is an `article` labelled "Post content" (or "Transcript").
- Read, star and errors are announced in a polite live region.
- Tooltips fade in 125ms; none under reduced motion. No other motion (P12).

## Decisions

- 003 reading-only, 004 one centred column with icon actions, 007 no fetch in reading views, 011 the source name links into Sources (`../decisions.md`).

## Open issues

- Reddit posts still offer "Fetch comments / Refresh comments", which is fetching in a reading view (P7). Not yet filed.
- The YouTube line shows view and like counts and the transcript source (P6). Not yet filed.
- Title wrap `pretty` vs `normal` is the seed prototype (D6).
- [0004](../../../../../plan/issues/0004-citation-graph-sources-of-truth.md): links between posts (analysis).
