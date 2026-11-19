# Base judge (Mark X 0234, prompt derive-v1)

A news reader links named things (models, products, software) to what they are built on. Each item shows one POST (its date, source, title and the part of its text that names both things) and two things the post names: A and B. A reading of the post said A is the post's subject and B is its predecessor: an earlier thing A comes after. That reading is often loose. Say what the post itself states about A and B. The reader sees your answer as "A is based on B", so call it only when the post says so.

## The relations (pick the first that fits)
1. `derived`: the post states that A is made from B. A is a fine-tune, a quantisation (GGUF, AWQ, MLX, 4-bit weights...), a distillation, a merge, a LoRA, a fork, a port or another derivative of B; or A is built on B's weights or code; or A runs on B as its base model or engine (a product "powered by B", an app "built on B"). A new version counts only when the post says it was made from B (continued training of B, B's weights upgraded), not merely that it came after B.
2. `replaces`: A is a newer version, a successor or a replacement of B (the post says A follows, supersedes, replaces or upgrades from B), and the post does not say A is made from B. People moving from B to A is `replaces` too.
3. `compared`: the post compares A with B (benchmarks, A beats B, A vs B), and nothing more.
4. `other`: anything else: A uses B as a tool or a part without being built on it, B is A's maker or platform, the two are named in separate parts of the post (two items of a list or a digest), one of them is not really a thing, or the post does not say how they relate.

## How
- Judge the post's words, not what you know: a relation true in the world but not stated in the shown text is `other`.
- Order matters: if the post says B is made from A, that is not `derived` (answer `other` and say "reversed").
- When you hesitate between `derived` and anything else, answer the other.
- Write `reason` first: one short sentence quoting or naming what in the post decides it.

## Output
One JSON line per item: {"id": "<id>", "reason": "...", "relation": "...", "confidence": 0-100}
