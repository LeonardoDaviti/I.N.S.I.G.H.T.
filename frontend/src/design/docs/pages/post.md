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
- **Reading time** runs while the post is current and the tab is visible, and is sent when it stops being current (1 s or more).

## Anatomy

- **Post navigation** (`PostNav`, ghost buttons, `sm`): Back / Back to feed; with a context, Previous and Next. It is a sticky band under the top bar (`reader-material`, `top-topbar`, like the reader toolbar), on one line at every width, so leaving or moving on never needs a scroll up. It sticks without animation.
- **After the post:** the same actions once more at `lg` (a tap target), below a hairline at the end of the column. Continuous, they come only after the last post of the feed, under "You’re all caught up".
- **The stream** (continuous): near the end of the last post the feed's next post joins below (newest first, the same scope and filter, as Next), after a `border-strong` divider with its source and title in `small` `text-3`. The post crossing the screen's midline is current: the URL follows it (replaced), and the sticky navigation, `m`, `s` and the tab title act on it. At most three posts are mounted (previous, current, next); one further away keeps its height. Room of half a screen under the last post lets it reach the midline. Images load lazily as they come near.
- **Header:** one line of byline in `small` `text-2`: the source name (a quiet link to its feed, `/read/source/<id>`), ` / settings` in `text-3` (a quiet link to `/settings/sources?source=<id>`, P8), ` / platform`, ` / date` (each "/ part" wraps as one). At its right the actions, icon-only with tooltips (P5): ↗ open original (when there is a URL), 💬 open discussion (when the feed names one, e.g. the Hacker News thread), ☆ star, ⧉ copy text (✓ "Copied" for a moment).
- **Title:** `h1` at the display step (1.75rem, 2rem from sm), weight 650, `text-pretty`, `dir="auto"`. It is the API's short title, as given: the first line of the title (or of the body, when the title is empty or the body's start cut with "…"), cut over 120 characters at the first sentence end, else at a word with "…". The feed rows show the same title. The tab reads `<title> · INSIGHT`.
- **Hero media:** the first image as a figure, or an embedded video in a reserved 16:9 frame.
- **Body:** the content in full (a body that is exactly the title is not repeated) as wrapped prose through `MarkdownRenderer` at the reading measure (~68ch); monospace only for real code blocks, which scroll on their own. A post with no HTML body shows its stored plain text read as markdown only: a literal `<details>` in it is text, never an element.
- **More images** after the body.
- **YouTube posts:** the player, a line of duration / views / likes / transcript source, a "Watch progress" card (progress bar, position slider, Save progress, Mark complete), then the transcript in collapsed blocks with "Set progress here" and "Open at m:ss".
- **Reddit posts:** a "Discussion" section with the stored comments.
- Column: `grid-cols-[minmax(0,42rem)]`, centred, page `max-w-6xl`, `pb-24`.

## States

- **article:** a text post: byline, title, prose.
- **media:** a hero image, more images after the body, and a video (YouTube embed or watch mode).
- **long-title:** a title of several lines (up to 120 characters from the API) wraps, never truncated further, and balances with `pretty`.
- **headings:** a body using h1–h6, lists, quotes, tables and code, to check the prose scale.
- **missing-title:** a Telegram or commit post with no real title, or a tweet whose whole text is the title: the H1 is the text's first line or first sentence.
- **loading:** a skeleton in the same frame and column as the loaded page, so nothing jumps on arrival.
- **error:** "Post not found" with the error message and "Back to the feed". An action that fails (star, copy) shows an error `Notice` with Dismiss above the body.

## Interactions & keys

- `j`/`k` next / previous post in the feed (with a context), `u`/Esc back, `m` toggle read, `s` star, `?` the shortcut table. In the stream, `j`/`k` (and Next / Previous) jump to a post already there, instantly (P12); past its ends they open the post, which starts a new stream at the top.
- Prev/next and the stream replace the history entry, so Back leaves the post rather than walking every post read.
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

- 003 reading-only, 004 one centred column with icon actions, 007 no fetch in reading views, 011 the source name links into Sources, 020 the byline's source name reads the source and the navigation sticks, 021 continuous reading (`../decisions.md`).

## Open issues

- Reddit posts still offer "Fetch comments / Refresh comments", which is fetching in a reading view (P7). Not yet filed.
- The YouTube line shows view and like counts and the transcript source (P6). Not yet filed.
- Title wrap `pretty` vs `normal` is the seed prototype (D6).
- [0004](../../../../../plan/issues/0004-citation-graph-sources-of-truth.md): links between posts (analysis).
