# 0032 — Reading fidelity: know when INSIGHT reads a page worse than the site shows it

Status: **ready-for-agent** (owner, 2026-10-28: "would you prevent that ever happening in the future? how?").

## What happened
- The owner compared anthropic.com/news/2026-us-midterms with INSIGHT's copy: no images, and it opened with "Chapter 01: Connecting people to trusted sources".
- Causes, both in the shared article reader (`parsing.extract_article_html`, used by full text for RSS posts, page watch, saved pages and five site adapters):
  1. it kept only text blocks, so **every image inside an article was lost**;
  2. it didn't recognise a sticky table of contents as chrome.
- **Measured, not guessed:** 18 random page-read posts on the preview, re-read: 11 of 18 had been stored with 0 images while their pages had 7–30 (Apple Newsroom, the Google blog, 9to5google); 2 started with clutter (blog.google's share bar, 9to5google's topic list). NVIDIA looked wrong but wasn't: its other images are related-news cards. Fixed: 99f4b5d (images, table of contents), 251ba1a (component-part names).

## Why it wasn't caught
- The reader is heuristics (which block is the article, which class names are chrome) tested only on small hand-written fixtures. A fixture tests the rule its author thought of, never the site that breaks it.
- Nothing compares what INSIGHT kept with what the page shows, so a loss is silent until the owner happens to look.
- Each fix is tested on the case that triggered it; earlier fixes can regress (the review caught 1c07573 doing that).

## Prevention
1. **A corpus of real pages (S).** Save ~25 real article pages as test fixtures (trimmed only of scripts), covering the layouts seen so far: Anthropic, DeepMind, Meta AI, NVIDIA, Apple Newsroom, the Google blog, 9to5google, WordPress (Old New Thing), Substack, Ghost (Cloudflare), Hugo, Miessler's VitePress, borretti.me, Cohere, x.ai, Groq. For each, the expected title, first sentence, last sentence, image count, and words that must not appear (menus, share, "Chapter 01", "Related"). Every reader change runs against all of them, so a fix for one site can't silently break another. Refresh the corpus with a script (owner-run) when a site redesigns.
2. **A fidelity number on every page read (S).** When the reader keeps a page, record in the post's metadata how many images the page's main area had and how many were kept, and the kept text length. Ingestion logs and the source sheet show a source whose pages lose most of their images or start with very short blocks ("This source's pages lose images"), so the next loss is visible without anyone comparing by hand.
3. **Measure a proven extractor against the corpus (M, decision).** Mozilla Readability's algorithm (ports: readability-lxml) or trafilatura are years of real-site heuristics. With the corpus, compare INSIGHT's reader and one of them on the same pages (text kept, images, chrome left in). Adopt it only if it clearly wins; it is one dependency (0005 asks for a reason, and this would be one).

## Out of scope
- Re-reading every stored post. Posts read after the deploy get the fixed reader; the full-text repair (`repair_full_text --retry`) re-reads teasers only. A one-off "re-read page-read posts" option can follow if the owner wants old posts refreshed.
