# 0055 — "Covered by" on the post page, not only in the feed

Status: **built, not deployed** (2026-10-31) for v9.8 (owner, 2026-10-31: "when I read the post at the end, why I don't see covered by, I can only see covered by from the feed").

## The case
- **The post page shows nothing of a post's story,** though 0050 stores it: who else covered it, and in which role.
- **Readers miss it:** you read to the end, and the other sources are a step back, in the feed row.

## Decided
- **At the end of the post's text,** before the next post in continuous reading, one quiet block when the post is in a story with 2+ voices:
  - "Covered by 4" with each other post: source name, its title, its date, and "share" for a share;
  - the first reporter marked "first".
- **Each entry opens that post in INSIGHT.** Read posts look read, as in the feed's opened row.
- **Nothing when the post is in no story.** No new setting.
- **Data:** the post detail gains the story the feed row already gets (0050's `story` object, the same shape). It doesn't add a second way of computing it.
- **Out of scope:** stories by name surge (News only), and editing a story.

## Done when
- **Backend:** the post detail carries the story. Tests cover a lead, a member, a share, and a post in no story.
- **Frontend:** the block renders at the end, opens posts, and marks read ones. Tests and screens in light and dark, including a Russian/English story.
- **Checks:** the lab case `kimi-k31-pro` (`plan/research/lab/cases.json`) shows its 7 other posts on Simon's post. Bundle within budget: 130 bytes are left, so lazy-load or keep it tiny, and report the size.

## Built
- **Backend** (no migration):
  - `PostDetailService.story(cur, post_id)` gives the post detail its `story`: 0050's `ReaderRepository.attach_stories` on the one post, the same query and the same object as the feed row's, kept when the story has 2+ voices, else `null` (no story, or copies of one voice).
  - The object gains one field, for the feed and the post alike: `first`, the story's first report (else its first share), so the page can mark it.
- **Frontend** (`PostDetailPage.tsx`, `CoveredBy`):
  - after the text, its images and Background, before the Discussion and the next post in the stream: `Covered by 4` (`· this post was first` when it was), then the other posts as the feed's folded list shows them (unread dot, source, title opening the post in INSIGHT, `· share`, `· first`, date);
  - read posts look read; opening one, or marking one read or unread on its page, updates every cached post page's list;
  - nothing when the post is in no story;
  - written in the post page, not shared with `FeedItem`: importing the feed's list from the post page split the reader's chunks and added 235 to 307 bytes to its initial JS.
  - Design: `pages/post.md` has the block and a `story` state (Russian/English, 4 sources).
- **Tests:**
  - Backend `test_post_page.py`: the lead (the same object the feed row gets), a member, a share, read posts, a post in no story, and copies of one voice.
  - Frontend `PostDetailPage.story.test.tsx`: the list with `first`, `share` and read and unread entries, placed after the text; `this post was first`; an entry opens its post; an opened post reads as read in a cached post's list; nothing for a post in no story.
  - Suites, both issues together: backend **999 tests OK**; frontend typecheck, lint, **181 node + 645 vitest tests**, build OK.
- **Bundle:** the reader's initial JS is **479,685 bytes**, unchanged (+0 on the 479,685 before this issue; 0.97% against the 475,065 baseline).
- **Lab case `kimi-k31-pro` passes** (on `insight_lab`, read only): Simon's post shows its 7 other posts, 7 voices, Russian and English: ai_dispatch (first), data_whispers, seeall_notes, countwithkim, dennis_it (share), two r/LocalLLaMA posts (one a share). @data_whispers's post shows Simon's among its 7. The story lookup takes 1.4 ms a post (500 posts in stories).
- **Screens** (Design Studio frames, light and dark, 1400 and 390; not committed): `~/.cache/insight-checks/0055-0057-shots/story.*.png`.

## Left open
- **"Covered by N" counts sources**, as the feed's line does: the kimi story reads `Covered by 7` above 7 other posts, as r/LocalLLaMA has two posts and Simon's own post is one of the 7 sources.
- **Read state after the server's propagation:** opening a report reads the story's shares on the server (0050), but the cached lists only mark the post you opened; they catch up when they reload (5 minutes).
- No design decision was added (the block follows decision 035's list); `pages/post.md` records it.
