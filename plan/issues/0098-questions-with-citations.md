# 0098 — Questions with citations: answers drawn only from what you've received

Status: **future** (2026-11-04). Mark X, after Shadow's embeddings (0086 B) and entities (0090).

## What
- **Ask in plain words:** "What did Anthropic ship this quarter?", "Who reported the outage first?", "What changed in Qwen's licence?".
- **The answer comes only from your posts:**
  - every sentence carries its citations;
  - every figure and version is checked against the cited posts in code;
  - "your sources don't say" when they don't.

## How
1. **Retrieval:** BGE-M3 over every post (the HNSW index), filtered by entities and dates when the question names them, plus the graph's connections (0091) to pull in follow-ups.
2. **Writing:** Haiku writes, or Sonnet for long answers, from the retrieved posts only.
3. **The check:** like the briefing's (F12), every figure and version must occur in a cited post, or the line is dropped.

## Measure before adopting
- 30 questions you'd really ask, each answer labelled for correctness, support and completeness.
- Unsupported sentences must be 0.
