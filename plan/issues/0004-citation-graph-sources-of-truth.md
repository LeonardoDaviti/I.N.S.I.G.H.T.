# 0004 — Citation graph: which post cites which, and where the source of truth is

Status: **discussion** (owner, 2026-10-10). Future feature — don't build yet. Close to [0001](0001-entity-pages-and-milestones.md): an entity's *commentary* is this graph's "cited by".

## The example
Post `e6b0a82c-…`, "Quoting The New York Times" (Simon Willison, 10 Oct 2026), contains 8 links:

| Link | What it is |
|---|---|
| `nytimes.com/2026/10/09/technology/anthropic-rogue-ai-agents.html` (twice) | the article being quoted: the **direct parent** |
| `anthropic.com/research/investigating-unintended-model-actions` | the research the article is about: the **source of truth** |
| `simonwillison.net/tags/{accidental-cyberattacks, anthropic, generative-ai, ai, llms}` | the site's own tag navigation: **noise**, not citations |

## What happens today (facts)
- **Links are not extracted or stored.** They exist only inside `content` / `content_html`.
- `post_relations (from_post_id, to_post_id, relation_type, method, confidence, metadata)` already exists, but has **0 rows**.
- Posts already have `normalized_url`, `canonical_url` and `url_host`, so matching a link to a stored post is a lookup.
- No source covers `anthropic.com` yet, so the research post isn't in the system. The link would be **dangling** today.

## Sketch (for discussion, not decided)
1. **Extract outbound links at save time.** It's deterministic and needs no LLM.
   - Store `post_links (post_id, url, normalized_url, host, anchor_text, position)`, including links whose target isn't in the system yet.
   - Drop noise with rules:
     - the source's own tag, category and archive pages;
     - share and intent links;
     - tracking parameters.
2. **Resolve in both directions.**
   - A new post that cites a stored post creates a `post_relations(cites)` row.
   - A newly stored post that earlier posts already linked to (a dangling link) **back-fills** those relations. When the Anthropic post arrives later, Simon's post attaches to it.
3. **Parent vs source of truth.**
   - *Parent:* what the post directly quotes or reacts to (first and most-repeated link, "Quoting X").
   - *Source of truth:* the primary, official origin (the host is the subject's own domain, see 0001's "official" question). It may be several hops away: Simon → NYT → Anthropic.
   - Walking the chain gives you the origin.
4. **Reading UX (quiet):**
   - the post page gets **Cites** and **Cited by** lists;
   - an in-system target opens in the reader;
   - a dangling target shows its host and opens the original.
5. **Source discovery:** a URL cited by ≥ N of your sources but missing from the system becomes a suggestion: "6 of your sources cite anthropic.com/research — add it as a source?" This turns the graph into a way to find sources of truth.

## Open questions
1. Is link extraction **ingestion** (always on, structural) or **analysis** (behind `INSIGHT_ANALYSIS`)? Lean: ingestion, because it's metadata like `media_urls`.
2. How should the noise rules be maintained: per source kind, per host, or learned from "links that appear on every post of a source"?
3. Back-fill: run once over the existing corpus (thousands of posts) when this ships?
4. How should ties be shown? Several parents, or a cycle where two blogs cite each other.
5. Should the "source of truth" be stored or computed at read time? Lean: computed, like milestones (0017).
