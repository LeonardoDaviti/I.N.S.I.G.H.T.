# 0142 — Written by INSIGHT: a post's full report, and theme essays that connect months of news

Status: **future** (2026-11-09). **Not Stealth** (the owner: "too future feature"); after Stalker's graph (0131), search
by meaning (0141) and stored originals (0138). Prototype only: `plan/research/report-proto/` (private).

**The owner (2026-11-09):** on a dense 6-minute video: "can insight compose such blogs from the news itself … I want
to read full report of it, with insight linking, entities and so on." On a long-read that sums up a theme from many
sources: "can't we write such blogs in future? to connect things and write sum-ups, but first we need to understand
what this post presents."

## Two kinds of writing
### A. A post's full report (one dense post → its full story)
- **Input:** the post's full text or transcript; related posts by search, its entities and stories, its links and
  collected originals (0138); Mark X's readings.
- **Output:** a report page: summary; the story step by step with every term explained; "what the post glossed
  over" (each passing claim expanded, or marked "only this post says it"); the background it assumed; people,
  organisations and documents (linked to their entity pages); disagreements between sources; read next.
- **Prototype (2026-11-09, one Haiku call, ~38k characters in, ~2,700 words out):** a video's transcript plus 13
  related posts. Every sentence cited; 12 disagreements found the video hides (a different bound, a different method,
  a second lab's proof the video omits); two surprising claims checked against their sources: both held. It also
  showed the gaps: the paper itself was not stored (0138 E1), the video's entities not yet read, search order chose
  the related set (0139 / 0141).

### B. A theme essay (many stories over months → one connected long-read)
- **The model to learn from:** a human long-read (a Russian tech-site essay, 8 Nov 2026, ~20k characters) on "weird
  artifacts of machine minds in 2026": an intro, **5 numbered cases**, each a story cluster of 3–6 sources (research
  posts, investigations, news, a paper, a repository), a commentary voice, a closing that ties them together. **27
  linked sources over ~6 months; INSIGHT stored 3 of them** (measured by GET).
- **What the essay is made of (measured, 2026-11-09):** 27 links: research forums and an essay blog (6), an
  investigations outlet (5), tech news sites (6), a paper, a repository, an incident database, a research write-up,
  a psychology blog, two product links; ~6 months of dates; each case mixes **one primary** (a paper, an experiment,
  an investigation) with **its coverage** (2–4 news pieces) and **one commentary** (an essay), then the author's
  connecting line. **INSIGHT stored 4 of the 27**; 3 missed ones are pages of sources INSIGHT follows (the feeds
  didn't carry them); one outlet cited 5 times is already a Discover suggestion (26 voices) never followed.
- **So the first need is the sources, not the writer:** 0138 F (a long-read's references, a followed feed's missed
  pages) would have stored ~all 27; only then can INSIGHT write such a case.
- **The essay as a teacher:** each human theme long-read is also a labelled example — its cases are a gold
  grouping (which stories belong to one theme across months) and its links a gold "evidence set" per case. Kept as
  the B measure's set; Stalker's theme edges are scored on it.
- **What INSIGHT would need:** a **theme** (an entity, a Stalker graph region, or the owner's words); its **cases**
  (stories linked to the theme across months: 0131's edges, 0092 back-in-the-news); each case's **sources stored**
  (0138); the writer guide (B's sections: intro, cases, connections between cases, what it adds up to, open
  questions, read next).
- **Measured against the human essay:** for such long-reads INSIGHT stores (a set of 10), does INSIGHT's essay on the
  same theme find the same cases (recall), cite them right, and add cases the human missed?

## Shared rules
- On request (a button), as a worker task (`report` / `essay`, guides report-v1 / essay-v1), answered at the next
  run; later by the API.
- Every factual sentence cited; numbers and names checked against the cited source (perspectives' number check);
  uncited sentences dropped; "only <source> says this" kept visible.
- Entities and stories linked; the report is stored, versioned (a re-run after new posts is a new version), with
  label buttons (right / wrong / missed per section).
- Model: Haiku first (≈ $0.02–0.05 a report); a stronger model measured on the same set before any switch.

## Measure before building
- A: 20 dense posts (videos, podcasts, long threads); per report: claims right / wrong / uncited, disagreements found
  that are real, the owner's "would read it" label.
- B: the 10 human theme long-reads above; case recall, citation precision, cases added.
