# 0055 — "Covered by" on the post page, not only in the feed

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "when I read the post at the end, why I don't see covered by, I can only see covered by from the feed").

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
