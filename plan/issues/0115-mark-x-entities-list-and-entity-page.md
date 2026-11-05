# 0115 — Mark X entities: one list ranked like News, an entity page with all its sources and posts, nothing hidden when read

Status: **superseded by [0119](0119-mark-x-v10.1-entities-and-perspectives.md) A3** (2026-11-06): its list, page and decisions are built there. Was: **spec** (2026-11-05, the owner, from the live `/markx` page). Not built. Mark X (Shadow's page); builds 0090 part F's first step.

**The owner (2026-11-05):** "I don't like the entities page, I want to click on entity and see all the sources and posts, or without clicks they should be sorted just like we have in news. And I don't like that they are divided into today and weeks, and posts and stories disappear when I read them from entity, don't do that."

**Constraints:**
- Mark X's tables only (`mx_mentions` with 0090's name key, `mx_readings`, `mx_story_posts`);
- Mark IX's pages are unchanged;
- no real names in committed files;
- read-only for the reader's state: viewing an entity marks nothing;
- the reader review before calling it done.

## Wrong today (v10.0, `markx/news.py: entities()`, `MarkXEntities`)
1. **Split into "Today" and "This week"** (1 and 7 days), the top 30 each. The same entity appears twice, and a story older than 7 days vanishes from the tab.
2. **Only main-subject mentions count** (`role = 'subject'`). A post where the entity is compared, mentioned, ranked, used as a tool or supported in (0090's roles) never reaches it.
3. **At most 3 example posts per entity, picked arbitrarily:** the first 5 post ids in uuid order (`array_agg(DISTINCT post_id)[1:5]`), not the newest or the strongest. Each refresh may show different posts.
4. **The entity can't be opened.** There's no page with all its posts and sources.
5. **Posts disappear once read** (the owner, live). The entity tab must never hide a post or a story because it was read. Read ones are shown as read (dimmed), in place. Whatever hides them today (a read filter, or the arbitrary example pick of 3) is removed.

## Decided
1. **One list, ranked the way News ranks rows.**
   - The order: distinct sources (voices) over the window, then reports against mentions, then recency of the newest post.
   - The same window as News (30 days; follows 0112's setting when the decision window grows).
   - No Today/Week split. Each row shows when the entity was last seen ("today", "3 days ago") as text, not as a section.
2. **A row shows:**
   - the entity (name, type, maker, and the exact version: GPT-6.1 Terra, not GPT);
   - its sources and posts counts;
   - its Mark X stories (headlines);
   - its 3 newest posts, newest first, never arbitrary.
3. **Click the entity: its page,** `/markx/entities/<name key>[/<version>]`:
   - **Every post** that names it, in every role (subject, compared, mention, ranked, used as a tool, supported in), with the role shown on each line.
   - **Grouped by its Mark X stories,** ordered like News: one block per story, its headline and sources, the posts inside by published time. Then the posts in no story.
   - **Every source** that wrote about it, with counts.
   - **Its family and versions** (0090's hierarchy): GPT-6.1 Terra's page links GPT-6.1 Sol and GPT-5.6 Terra, and the family page lists every version.
   - **Read posts stay,** shown as read. Nothing on the page marks a post read, except opening it, as everywhere.
4. **Never hidden by reading:** the entities list and the entity page ignore read state for what they include. Read state only changes how a line looks.
5. **From a post:** the post page's Mark X panel lists its entities, and each opens its entity page.

## Not in this issue
- Timelines across months: releases, papers and numbers in order (0090 F, 0095). They come with 0112 decision 9's 120 days of readings, as a second step on this page.
- Merging entity names (0090 C's merge queue), and surges as alerts (0090 E).

## Measure before building (the live server, by GET, after entities are read)
- How many entities and posts the 30-day list holds, and the page's size for the biggest entity. It must load in under 1 s on the server copy.
- How many posts the role filter hid: posts with only non-subject roles.
- The reader review on the real `/markx`: the owner's three complaints are the cases. One list, no split; click opens all posts and sources; reading a post never removes it.
