# 0087 — A local Mark X: Gemma 4 E4B fine-tuned on Haiku's answers

Status: **future** (the owner, 2026-11-04: "save this as future feature, we really go do the fine-tuning"). Don't build yet. It needs 0086 running first: 0086 stores the answers this trains on.

**Constraints:** INSIGHT itself stays free of PyTorch and runs the result as a GGUF file in llama.cpp; only the one-off training job needs a training stack. Scored on your labels only, never on Haiku's.

## Why
- Haiku governs Mark X first (0086). A local model keeps your posts on your machines and costs nothing per call.
- Measured on the server's posts (prototype, Claude labels, 2026-11-04), untrained Gemma 4 E4B is far from Haiku:

  | Task | Haiku | Gemma 4 E4B |
  |---|---|---|
  | Reading's kind | 86.7% | 76.9% |
  | Ranking wrong joins | 0.80 | 0.64 |
  | Joins and new stories right | 98% | 65% (45% on held-out days) |

  Its main error is reading "same product" as "same event", a boundary that training on labelled examples fixes well.

## What to train, and on what
- **The narrow decisions:**
  - the reading (kind, events, slots);
  - the check (is this member about its story?);
  - joins and new stories.

  10–20k examples are plenty for these.
- **Not first:**
  - Russian translation, headlines and briefings (open writing);
  - merges and connections across stories (rare, and they need product and version knowledge).

  They stay on Haiku.
- **The examples build themselves** from 0086's `mx_calls`: every Haiku call with its input, answer and prompt version.
  - At today's rate (about 200 readings and 45 questions a day), 10k readings take about two months.
  - A backfill is faster: 20,000 posts read by Haiku cost about $6 at Haiku 5.5's $0.10 / $0.50 per million tokens, $3 with the Batch API.
- **The split is by date:**
  - train on the older days;
  - pick the bars on a middle slice;
  - test on the newest days and on your labels (E1).

  A model scored on Haiku's own labels looks better than it is.

## Where and how
- **Not on the server's GPU.** Unsloth's guide puts Gemma 4 E4B fine-tuning at about 10 GB of GPU memory even with 4-bit training (QLoRA), and about 17 GB for 16-bit LoRA. The server's GTX 1660 Ti has 6 GB and no bf16.
- **Train once elsewhere:** a rented GPU for a few hours, or the workstation. Then export to GGUF (q4).
- **The stack:** Unsloth / TRL are PyTorch. It is used for the training job only, outside INSIGHT.
- **Serving on the 1660 Ti is tight:** the 4-bit file alone is about 5.2 GB, so expect some layers on the CPU. Speed is E8's question.

## Cheaper steps to try first (they may be enough for some tasks)
1. **Examples in the prompt:** the 3–5 nearest labelled questions (BGE-M3) shown with each new one. No training.
2. **A small classifier on top** (scikit-learn, no PyTorch, CPU, milliseconds), trained on Haiku's answers. Its inputs:
   - the similarity;
   - the readings' slot matches (same company, product, version, date);
   - shared names;
   - the model's own probability.

   Its confidence can be calibrated, so a cascade can trust it.
3. **A cascade:** the local model decides what it is sure of; Haiku gets the rest, plus merges, connections and translation.
4. **Gemma 4 26B-A4B with its experts in system RAM** (llama.cpp keeps a mixture-of-experts model's experts on the CPU). Untrained, it already checks as well as Haiku (0.81). It needs the server's CPU and RAM (E8).

## Done when (for when this is built)
- On your labels, the fine-tuned model is within a set margin of Haiku on each task it takes over (the margin is decided with the owner before training), on the newest days.
- In a cascade, the share of tasks that still go to Haiku is measured, and nothing gets worse on your labels.
- INSIGHT runs it as a GGUF in llama.cpp, with no PyTorch.

## Can it match Haiku fully?
- **Likely close:** reading, checks and joins.
- **Unlikely:** Russian translation, writing, and the rare merges and connections.

The goal is the bulk done locally and the hard and rare parts on Haiku.

Sources: [Unsloth: Gemma 4 fine-tuning guide](https://unsloth.ai/docs/models/gemma-4/train).
