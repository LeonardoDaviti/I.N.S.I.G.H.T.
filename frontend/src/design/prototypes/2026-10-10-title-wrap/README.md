```meta
hypothesis: Normal wrap fills the post title's first line (about 90% of the column) and reads better than the shipped pretty wrap (about 82%)
principles: P1, P4
page: post
states: long-title, article
status: review
created: 2026-10-10
```

# Post title: normal wrap

The post page's `h1` wraps with `text-wrap: pretty` today: the browser shortens the first line (about 82% of the column for "A new feature for my blog, built using my voice") so the last line never holds a single word. This prototype tries plain `text-wrap: wrap`: the first line fills to about 90%, at the risk of a one-word last line.

## What changes

- The post title only: `text-wrap: wrap` instead of `pretty`.
- Nothing else: size, weight, leading, the byline, the actions and the body headings (which keep `pretty`) are the shipped page.

## Compare on

- **long-title:** a title of several lines, where the last line is the risk.
- **article:** an everyday short title, one line at 1400 and two at 390, like the title the question started from.

Judge at 1400 and at 390: at phone width the one-word last line is likeliest. It serves P4 (one centred column the eye never hunts in) and P1 (the title is the first thing you read).

## If accepted

The post page's `h1` swaps `text-pretty` for `text-wrap: wrap`, `pages/post.md` changes as `doc.diff` shows, the folder is deleted and the decisions log gets a line.
