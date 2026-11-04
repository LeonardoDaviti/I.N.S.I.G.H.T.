# 0089 — A shared link's 72 hours count from the page's first-ever link

Status: **measured, not adopted** (2026-11-04). It waits for the same-story labels (Mark X experiment W): about half of the joins a fix would add are wrong, and the wrong ones are a meaning-level problem.

## The rule today
- `story_rules.py`, the shared-link join: `near = [p for p in ps if p.t - ps[0].t <= LINK_WITHIN]`.
- The window opens at the page's first linker ever. A later burst of posts linking the same page, hours apart from each other but weeks after the first link, never joins.
- Citations compare each pair (`abs(p.t - cited.t)`), so they don't have this gap.

## Measured on the lab (41,637 posts; the app's own full job with each variant)

| | A, today | B, bursts | C, chained |
|---|---|---|---|
| how the window is counted | from the page's first-ever link | a new window opens at the first link not yet in one | each link within 72 h of the one before |
| stories with 2+ sources | 713 | 730 | 730 |
| posts whose story changes | — | 81 | 143 |
| posts that leave a story | — | 0 | 0 |
| News rows changed | — | 3, all wrong | 5 |
| Classics | 182 | identical | identical |

- **B, read by hand (26 bursts that change membership):** 14 right, 3 borderline, 1 mixed, 8 wrong (54% right).
- **The wrong ones are one kind:** websites linking a lab's announcement as background days or weeks later (essays, monthly link roundups). Today's rule avoids them only because it never looks past the first 72 hours.
- **C:** no better than B, and its reach is unbounded on pages linked every day (one account links one page daily: a 21-day chain from one place, which one outside post would turn into a 24-post story).

## Decided
- **Nothing changes now.** Telling a fresh burst about an old page from a later essay that uses it as background is a question of meaning, so it waits for the same-story check (Mark X step 1, experiment W's labels).
- **When it changes, it's B,** judged against today's first-window joins by the same standard.
- **For the incremental job:** each burst becomes its own page node, stored in `post_edges`, and the readers of page nodes (`stories_holding`, `linking`, `pages_linked`, mentions, `_grows`) learn burst nodes. Discover's origins count a page once.
- **Also found:** a page can carry a link newer than its own date (a post's "Update, 30 September" paragraph). The link's time is the post's date, so it counts too early. That's the same class as 0076's dates; it's noted for the post parser (links with a time of their own).

The measurement is kept privately in `plan/research/link-window/`.
