# 0001 — Entity pages with personalised milestones

Status: **discussion** (owner, 2026-10-10). Future feature — don't build yet. Belongs to the analysis version (after Mark IX).

## What the owner wants

- **Click a company name** (e.g. *Anthropic*) anywhere milestones show it, and land on a full page about that company.
- The page collects:
  - **Official posts:** everything the company itself published (blog, research, release notes, changelogs).
  - **Commentary:** opinion and analysis posts *about* those official posts, from the owner's own sources.
- A **milestones tab** on the page, personalised to the company. Milestones are more than model releases:
  - **Model releases** (Claude Opus 5.5, Haiku 5.5, …): what exists today; fast to build.
  - **Research / safety publications**, e.g. <https://www.anthropic.com/research/glm-5-3-and-the-spread-of-advanced-cyber-capabilities>. That one *is* a milestone.
  - **Engineering**: products, tooling and infrastructure posts.
  - More lanes later; the categories are open.

## What exists today (facts, 2026-10-10)

- **Milestones are not stored and not derived by a job.**
  - `milestone_lanes` (migration `0017_milestones.sql`) holds one regex per lineage, e.g. `claude haiku`.
  - A milestone is `(lane, version)` grouped out of `posts` **at request time**.
  - So a new post that mentions "Claude Haiku 5.5" shows up as soon as it's fetched. That's why Haiku 5.5 (Oct 7) appeared after the last fetch, with analysis switched off.
- **Lanes are model lineages only** (e.g. "Claude Haiku", "Claude Sonnet"). There is no company → lanes grouping yet, and no notion of an "official" source.
- **Entities exist:** `entities`, `entity_aliases`, `entity_mentions`, `post_entities`, `events`, `event_entities`, `event_evidence`, filled by the rule-based `Enricher` on every save batch. With `INSIGHT_ANALYSIS=off` (reading-finish S2) that enricher becomes a no-op.

## Open questions for the discussion

1. **"Official":** how do we tell a company's own post from commentary? A per-source "official for entity X" flag, or the URL host (`anthropic.com`, `openai.com/index`)?
2. **Lane types:** fixed (model / research / engineering / product) or free per company?
3. **Non-version milestones:** research posts have no version token, but the lane regex needs exactly one capture group. Use a different matcher (title + host), or a manual "mark as milestone"?
4. **Commentary linking:** only by mention (the entity's name appears), or must the post link to the official URL?
5. **Coverage:** do official sites need new sources (Anthropic news / research RSS), or are mentions in existing sources enough?
6. **Where it lives:** its own route `/entities/:slug`, reached from milestones, post pages and ⌘K?
