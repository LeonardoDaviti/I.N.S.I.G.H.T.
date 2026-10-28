```meta
kind: page
routes: /posts/:postId
states: article, media, long-title, headings, missing-title, loading, error
```

# Post

Code: `pages/PostDetailPage.tsx`, `components/post/*` (`PostActions`, `PostImages`, `PostNav`), `components/ui/MarkdownRenderer.tsx`. The title comes from the backend's `display_title`.

## Purpose

Read one post, whole, in one centred column with nothing beside it (P4). It is the content and its actions; nothing else. Read continuously, the next posts of the same feed follow below it, like a comic you keep scrolling.

## Entry & URL

- `/posts/:postId`, opened from a feed row (title link, `o`/Enter) or a link elsewhere.
- `?ctx=` carries the feed it came from (scope, filter, page cursor), so prev/next and "Back" survive a reload. Without it there is no prev/next and the way out reads "Back to feed".
- Dev-only `?data=worst|empty|missing|slow` swaps in fixtures.
- The post loads through `usePost`, so a post the feed prefetched opens from cache with no skeleton.
- **Flow** (`insight.reader.flow`, chosen in the reader toolbar, `continuous` by default): continuous needs a `?ctx=`; without one a post stands alone.
- **Read:** one at a time, opening a post marks it read. Continuous, a post is read once its end has passed the top half of the screen (an end already above the midline counts at once), the first post too. The feed's cached rows and counts follow.
- **Finished** (decision 029): in either flow, once the post's end passes the top half of the screen (the same moment), a post in Later leaves it; so does marking it read (`m`). Opening it does not, even one at a time, where opening marks it read.
- **Reading time** runs while the post is current and the tab is visible, and is sent when it stops being current (1 s or more).
- **Where you stopped** (issue 0030): a long post (4,500 characters or more, about three screens; not a video) stores the index of the top text block in view of its body and the body's block count, on the server with its read state. A block, not a scroll offset, so images and widths do not move it. Saved 3 s after scrolling stops and at once when the tab hides or the post leaves; nothing before you scroll. Cleared once the end passes the top half of the screen (when the stream counts it read) and by marking it read. In the stream each post keeps its own.

## Anatomy

- **Post navigation** (`PostNav`, ghost buttons, `sm`): Back / Back to feed; with a context, Previous and Next. It is a sticky band under the top bar (`reader-material`, `top-topbar`, like the reader toolbar), on one line at every width, so leaving or moving on never needs a scroll up. It sticks without animation.
- **After the post:** the same actions once more at `lg` (a tap target), below a hairline at the end of the column. Continuous, they come only after the last post of the feed, under "You’re all caught up" (Show unread) or "You’ve reached the end" (Later, Kept or All, as the list says).
- **The stream** (continuous): near the end of the last post the feed's next post joins below (newest first, the same scope and filter, as Next), after a plain `border-strong` rule (its own header names its source and title). Only the first post's byline carries ` / settings`; a post that follows reads source / date (decision 027). Each post keeps its own actions, since star and copy act on that post. The post crossing the screen's midline is current: the URL follows it (replaced), and the sticky navigation, `m`, `s`, `l` and the tab title act on it. At most three posts are mounted (previous, current, next); one further away keeps its height. Room of half a screen under the last post lets it reach the midline. Images load lazily as they come near.
- **Header:** one line of byline in `small` `text-2`: the source name (a quiet link to its feed, `/read/source/<id>`), ` / settings` in `text-3` (a quiet link to `/settings/sources?source=<id>`, P8), ` / date` (no platform: the source says it, P6; this year's dates without the year, the full date and time in its tooltip, decision 028) (each "/ part" wraps as one). At its right the actions, icon-only with tooltips (P5): ↗ open original (when there is a URL), 💬 open discussion (when the feed names one, e.g. the Hacker News thread), 🕓 read later and ☆ keep (both offered whatever the read state; decision 029), ⧉ copy text (✓ "Copied" for a moment).
- **Title:** `h1` at the display step (1.75rem, 2rem from sm), weight 650, `text-pretty`, `dir="auto"`. It is the API's short title, as given: the first line of the title (or of the body, when the title is empty or the body's start cut with "…"), cut over 120 characters at the first sentence end, else at a word with "…". The feed rows show the same title. The tab reads `<title> · INSIGHT`.
- **Continue line** (only the post opened, not one joining the stream): between 5% and 90%, under the header, a quiet `text-link` button in `small` `text-2`: "Continue from where you stopped (40%)". It scrolls to that block and moves focus there; reading past the old place (or the end) removes it. Nothing scrolls by itself.
- **Hero media:** the first image as a figure, or an embedded video in a reserved 16:9 frame.
- **Body:** the content in full (a body that is exactly the title is not repeated) as wrapped prose through `MarkdownRenderer` at the reading measure (~68ch); monospace only for real code blocks, which scroll on their own. Tables keep their header cells, rows and columns, in a hairline frame; a figure keeps its image with its caption under it, in `text-2` at 0.875em (issue 0042). A post with no HTML body shows its stored plain text read as markdown only: a literal `<details>` in it is text, never an element.
- **More images** after the body.
- **YouTube posts:** the player, a line of duration / views / likes / transcript source, a "Watch progress" card (progress bar, position slider, Save progress, Mark complete), then the transcript in collapsed blocks with "Set progress here" and "Open at m:ss".
- **Reddit posts:** a "Discussion" section with the stored comments, only when some are stored; there is no "Fetch comments": Reddit refuses it (issue 0012), and its backend is removed (issue 0029).
- Column: `grid-cols-[minmax(0,42rem)]`, centred, page `max-w-6xl`, `pb-24`.

## States

- **article:** a text post: byline, title, prose.
- **media:** a hero image, more images after the body, and a video (YouTube embed or watch mode).
- **long-title:** a title of several lines (up to 120 characters from the API) wraps, never truncated further, and balances with `pretty`.
- **headings:** a body using h1–h6, lists, quotes, tables (one wide, with a caption), a captioned figure and code, to check the prose scale.
- **missing-title:** a Telegram or commit post with no real title, or a tweet whose whole text is the title: the H1 is the text's first line or first sentence.
- **loading:** a skeleton in the same frame and column as the loaded page, so nothing jumps on arrival.
- **error:** "Post not found" with the error message and "Back to the feed". An action that fails (keep, Later, copy) shows an error `Notice` with Dismiss above the body.

## Interactions & keys

- `j`/`k` next / previous post in the feed (with a context), `u`/Esc back, `m` toggle read, `l` toggle read later, `s` toggle keep (the star), `?` the shortcut table (without a context its post column has no `j`/`k`). In the stream, `j`/`k` (and Next / Previous) jump to a post already there, instantly (P12); past its ends they open the post, which starts a new stream at the top.
- Prev/next and the stream replace the history entry, so Back leaves the post rather than walking every post read.
- Read later is optimistic and rolls back on failure; keep shows once the server answers. Copy puts the stored text (or the HTML's text) on the clipboard.

## Worst cases

- Unbroken URLs and long words wrap (`break-words`, `[overflow-wrap:anywhere]`); the column is `min-w-0`, and `<pre>` and a wide table scroll inside themselves, so nothing widens the page past the viewport.
- The source name middle-truncates at 40 chars, full name in `title`.
- RTL and mixed-script titles via `dir="auto"`.
- A post with no content: an empty body, still readable header. A video with no transcript says so.

## A11y & motion

- Header actions are a labelled group; each icon has an `aria-label` and a tooltip; read later and keep are `aria-pressed`. Key presses do not trigger the press scale (only pointer presses do).
- The body is an `article` labelled "Post content" (or "Transcript").
- Read, Later ("Saved for later", "Removed from Later"), keep ("Kept", "No longer kept") and errors are announced in a polite live region.
- Tooltips fade in 125ms; none under reduced motion. No other motion (P12).

## Decisions

- 003 reading-only, 004 one centred column with icon actions, 007 no fetch in reading views, 011 the source name links into Sources, 020 the byline's source name reads the source and the navigation sticks, 021 continuous reading, 025 continue where you stopped, 029 read later and keep, 027 `settings` on the stream's first post only, 028 the byline date without this year (`../decisions.md`).

## Open issues

- The YouTube line shows view and like counts and the transcript source (P6). Not yet filed.
- A Telegram title cut with "[...]" by the feed bridge repeats the start of its body under the H1 (issue 0033 notes it; the title is the backend's).
- Title wrap `pretty` vs `normal` is the seed prototype (D6).
- [0004](../../../../../plan/issues/0004-citation-graph-sources-of-truth.md): links between posts (analysis).
