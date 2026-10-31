# 0065 — Discover suggests the sources your stories start from

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: on storing origin pages, "no, suggest source in discover"). Builds on 0064's outside roots and 0062's Discover in SQL.

## The case (the lab, the server's data)
- **The origins of your stories are mostly pages you don't follow.** Of 358 stories with a page linked by 2+ of their posts, 326 have that page outside your sources (0064). By site:
  - openai.com originates 42 stories, huggingface.co 42, github.com 33, anthropic.com 24, arxiv.org 22;
  - qwen.ai, claude.com and blog.google originate 7, 7 and 6.
- **Discover ranks by how many of your sources link a site.** It never says "this site starts the news you read".
- **Discover hides a site by its domain once any part of it is followed.** You follow `anthropic.com/research`, so Anthropic is never suggested, while `anthropic.com/news` originates 24 of your stories.
- **A followed site can still miss origins:** openai.com's feed holds only its latest 20 posts.

## Decided
- **"Origin of N stories" is Discover's first reason.**
  - Suggestions are ranked by the number of stories whose root (0064) is a page on that site or account, then by today's link counts.
  - The card says "Started 24 of your stories" with 2–3 of those stories, then "linked by N of your sources" as today.
- **Sections, not just sites:**
  - A site you follow in one section is suggested for **another section** that originates stories, using 0060's sections (`anthropic.com/news`: "You follow anthropic.com/research; /news started 24 stories").
  - Follow… starts the finder at that section (0060 already does).
- **Followed sources whose origins are missing:** when a followed source's own site originates stories whose pages aren't stored (older than its feed), its card in Discover says so and offers the archive (0015), not a second source.
- **Nothing is fetched until you follow.** No storing of origin pages (owner).
- **Out of scope:** popularity from outside (HN points, 0017).

## Done when
- **Backend tests:**
  - ranking by origins, then links;
  - a section suggested on a followed site;
  - a followed source with missing origins;
  - a site with no stories behaving as today.
- **On a copy of the lab:**
  - the top 15 before and after are recorded;
  - anthropic.com/news is suggested, with its 24 stories;
  - openai.com's missing origins are offered as an archive.
- **Frontend:** tests and screens, light and dark.
- **Checks:** suites green; budget within limits.
