# 0141 — Stalker: search by meaning, and ask INSIGHT a question with citations

Status: **spec, Stalker** (2026-11-09). Not built in Stealth. Follows 0139 (search finds: History, Mark X's English
layer, entities first). Takes over 0098 (questions with citations). Stalker is the graph tier (Remember + Reason).

**The owner (2026-11-09):** "I remember I found from post 3D library which makes agent to spend 3x less tokens on 3D
objects, and now I can't find it" → 5 (search by meaning) and 6 (ask Mark X) "will go in Stalker".

## Why
- 0139 makes words find posts in any language through Mark X's English layer. It still needs the words: "a tool that
  lets agents build 3D models cheaply" finds nothing if no post says "tool", "3D", "cheap".
- Every post already has a BGE-M3 vector (multilingual, 1024 dims), made by the Mark X embedder. Only the query lacks
  one: today the embedder runs on the owner's device.
- What the owner remembers is often a question, not a query: "what was that 3D library for agents?"

## What it does
### A. Search by meaning
1. **The query's vector on the server:** the same model (BGE-M3 Q8, CLS pooling) served on the server's CPU by
   llama-server, started by `./update` as its own container, used only by search (about 600 MB RAM; measure p50/p95,
   target < 150 ms). **Owner decision:** it is always on (it's not a worker; it only answers searches).
2. **Nearest posts:** pgvector (HNSW, cosine) on the stored vectors if the extension is available in the image; else
   exact cosine in memory over the newest N (measure the time at 70k posts).
3. **One ranking:** reciprocal rank fusion of 0139's word ranks (post text and Mark X layer) and the vector ranks;
   a vector-only hit needs cosine ≥ a measured floor; its snippet is Mark X's headline, marked "by meaning".
4. **Scoped as words are:** History, Later, Kept, a source, a folder, the last N days (0139).
5. **Off** when the embedder doesn't answer: words only, said on the page.

### B. Ask INSIGHT (0098)
1. A question box on the search page ("Ask"): retrieve with A (20 posts, plus matching entities and their stories),
   then **Haiku** answers in a few lines, every claim citing posts `[1]`, `[2]`; an answer it can't cite says so.
2. **First (Shadow-style):** the question is a task (`ask`, guide `ask-v1`), answered at the worker's next run; the
   answer shows on `/ask/:id` with its citations, label buttons (right / wrong / missed). About $0.002 a question.
3. **Then (the API phase of the Mark X plan):** the server calls the API with the owner's key; the answer streams in
   seconds. Same guide, same citations check.
4. **Checked, never trusted:** each citation must hold the claim's numbers and names (the number check of
   perspectives); an uncited sentence is dropped.

## Measure before adopting
- A: on 30 owner-style queries (the owner's remembered posts: private rows), page-1 recall words-only (0139) vs fused;
  latency. Adopt when fused finds ≥ 90% and words-only finds less.
- B: 30 questions, answers labelled: right and cited ≥ 90%, a wrong citation ≤ 2%.

## Open (the owner)
1. A1: the embedder always on, on the server (default yes when Stalker starts).
2. B: start with worker-answered questions (minutes), or wait for the API key (seconds).
