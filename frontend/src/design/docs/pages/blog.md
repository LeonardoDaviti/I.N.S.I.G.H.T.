```meta
kind: page
routes: /blog, /blog/:slug
states: index, article
```

# Blog

Code: `pages/BlogPage.tsx`, `blog/posts.ts` (the list), `blog/posts/*` (each body), `blog/components.tsx`, `blog/figures.tsx`.

## Purpose

How INSIGHT is built, in long posts the owner writes. A reading page like a post (P1, P4): one column, no fetch, nothing beside the text.

## Entry & URL

- `/blog`: the list, newest first. Reached from `blog`, the last word in the top bar (with analysis on or off), or ⌘K "Blog".
- `/blog/:slug`: one post. An unknown slug replaces itself with `/blog`.
- No API calls: the posts are code (`blog/posts.ts`), and a post's body loads as its own chunk when it opens.

## Anatomy

- **List:** `Page width="reading"`, a `PageHeader` "Blog" with a one-line meta, then one bordered block per post: date · minutes to read (`text-3`), title (600), summary (`text-2`). The whole block is the link.
- **Post:** a `BackLink` to the list, then a header of date · minutes and the title (`h1`, 1.75rem, 650), then the body in the reading column.

## States

- **index:** the list with its posts.
- **article:** one post open, its body loaded.

## Interactions & keys

- The list's blocks are links (Enter, click). The back link returns to the list. The app's global keys (⌘K, `?`) work as everywhere.

## Worst cases

- A long title wraps; the list block grows. A post's body is hand-written, so its worst cases are the post's own.

## A11y & motion

- One `h1` per page; dates are `<time>`. A list block's border answers hover in 120ms; focus shows the outline. Nothing else moves (P12).

## Decisions

- None logged; the blog shipped from main as an experiment.

## Open issues

- None.
