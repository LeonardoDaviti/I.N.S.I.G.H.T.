# Entity guide (Mark X F7, prompt ent-v3)

You index ONE post from a personal news reader (AI and tech; English and Russian are equal). List the named things the post talks about, so that posts can later be connected through them: the same company, the same model and version, the same person. Precision matters more than length: a wrong or vague entry connects posts that have nothing in common.

## What is an entity
A proper name of one specific thing:
- `org`: a company, lab, university, agency, government body, standards body or named community (Anthropic, NIST, the European Commission, Hugging Face the company).
- `person`: a named person.
- `model`: an AI model with its exact version and variant (Claude Opus 5.5, GPT-6.1 Terra, Qwen3.8-27B, Llama 4 Scout).
- `product`: a commercial product, service, app, device or chip (ChatGPT, Claude Code, iPhone 18, MacBook Pro, H200, Windows 7).
- `software`: an open-source project, library, framework, programming language, operating system or developer tool (PyTorch, llama.cpp, Linux 7.0, PHP 9, Rust, vLLM).
- `paper`: a research paper or report, by its title.
- `dataset`: a dataset or benchmark (SWE-bench Verified, ARC-AGI-3, MMLU).
- `event`: a named event (WWDC 2026, NeurIPS 2026, the 2026 Brazilian elections).
- `place`: a country, city or region, only when the news happens there or is about it.
- `law`: a law, regulation or named policy (the EU AI Act).
- `other`: a named thing that fits none of these.

**Not entities:** descriptions and noun phrases ("a video of a man running 8 agents", "$518B compute commitments", "the new model", "an unlimited plan for 512 RUB"); generic words (AI, LLM, agents, open source, GPU, startup, users); topics; hashtags; bare URLs; numbers and prices. A plan, price, benchmark score or feature is a detail of a product, not an entity.

## Each entity
- `span`: the exact words in the post that name it, copied character for character from the post (title, text or a link's words), in the post's language and spelling. Copy, never translate or fix it.
- `name`: its full canonical name in English, as its maker writes it.
  - Complete a short form only when the post itself makes it clear: "Opus 5.5" in a post about Anthropic is "Claude Opus 5.5"; "Астра" in a post about GPT-6 is "GPT-6 Astra"; "Антропик" is "Anthropic"; "Цукерберг" is "Mark Zuckerberg".
  - Never add a version or variant the post doesn't state, and never "correct" a version you don't know: a post saying "Grok 4.7" means Grok 4.7.
  - No descriptions, job titles or roles inside the name: "Cui Tianyi", not "Cui Tianyi, DeepSeek Harness lead".
- `type`: one of the types above.
- `role`: how this post uses it (exactly one):
  - `subject`: what the post is mainly about: the thing released, announced, found, reviewed or discussed; the company or person the news is about. Usually one per post; two or three only when the post is equally about them (a merger, a head-to-head comparison, two launches told as one).
  - `actor`: who does the main thing when the subject is something else ("OpenAI released GPT-6.1": GPT-6.1 is the subject, OpenAI the actor).
  - `compared`: named as a benchmark comparison or a competitor ("beats GPT-6.1 Sol on SWE-bench").
  - `predecessor`: an earlier version named as the base or the one replaced ("K3.1 replaces K3"; "fine-tuned from Llama 4").
  - `venue`: where the thing was published, posted, reported or discussed, when it is not the subject (Hacker News, arXiv, a news agency, a conference, a podcast).
  - `mention`: any other passing mention, background or example.
- `maker`: for a model, product or software: the org or person that makes it, canonical, when the post states it or it is unambiguous (Claude → Anthropic, Qwen → Alibaba); else null. Null for other types.
- Version fields, for anything whose name carries a version or size (else all null):
  - `family`: the name without version, variant, size or build ("Claude Opus", "GPT", "Qwen", "Kimi", "Linux", "iPhone", "DeepSeek").
  - `version`: the version exactly as in the name ("5.5", "6.1", "3.8", "K3.1", "V4.1", "7.0", "18", "4"), or null.
  - `variant`: tier or edition words ("Terra", "Pro", "Flash Next", "Instruct", "Mini", "Scout"), or null.
  - `size`: a parameter count ("27B", "8x7B", "1T-A52B", "2.6B"), or null. A size is never the version.
  - `build`: a quantisation, file format, checkpoint date or build tag ("GGUF", "Q4_K_M", "EXL3", "1017"), or null.

## Rules
- **Always list what the post is mainly about** (role `subject`), even if it is small, unknown to you, not a company or product, or has no version: a lab's own tool, a repository, a visa programme, a country the news is about, a named feature. A post whose subject is a named thing never ends without it. Only a post about no named thing at all (a joke, a general thought) has no subject.
- Concepts, techniques and methods ("ReAct", "chain of thought", "a named bug") are not entities unless they are a named product or project. A city only named as where something takes place is not an entity.
- One entry per thing. Never two things in one entry: "DeepSeek V4.1 Flash and GLM-5.3" is two entries.
- Different versions or variants are different entries: GPT-6.1 Sol and GPT-6.1 Terra; Kimi K3 and Kimi K3.1 Pro.
- The post's own source (its channel, account or site) is not an entity unless the post is about it.
- List every named thing a reader might want to follow, but at most 20; keep subjects, actors and anything with a version first.
- English and Russian are equal. `name` is always written in Latin script.

## Relations
Facts the post itself states between its entities (not your background knowledge), by their `name`: `{"a": "...", "rel": "...", "b": "..."}` with `rel` one of:
`released` (a makes and ships b), `announced` (a announces b, not yet out), `acquired`, `invested_in`, `partnered_with`, `sued`, `hired` (an org hires a person), `joined` / `left` (a person joins or leaves an org), `leads` (a person leads an org), `based_on` (model b is the base of model a), `beats` (a outperforms b, as the post claims), `part_of` (a is part of b). `[]` if none.

## Output
One JSON object: `{"id": "<id>", "entities": [{"span": "...", "name": "...", "type": "...", "role": "...", "maker": null, "family": null, "version": null, "variant": null, "size": null, "build": null}], "relations": []}`. An empty list is fine.
