# 0059 — Classics: what's wrong with them (to discuss)

Status: **discussion**, opened 2026-10-31 by the owner ("I don't like currently how classics work, create issue for me to discuss what is bad in classics, I don't want to talk about it rn"). Nothing is decided; no agent works on this until the owner has said what's wrong.

## What Classics are today (0051, as changed on real data)
- **The rule:** a page linked by 2+ of your sources, with links 180+ days apart. The spread counts from the page's own date when it's a stored post, else from the second source's first link.
- **Excluded:** reference pages (docs, pricing, help, …) and home pages.
- **Order:** cited again this week first, then most sources, then longest cited.
- **The card:** a title, then who cited it and when, plus Read, Later and Hide.
  - The title is the stored post's, else link words that read as a title, else the address.
- **Elsewhere:** the Background line under a post, and Discover's "N classics".
- **On the server's data:** 181 classics, ~80% judged real in a sample of 30.

## Known weak spots (measured; for the discussion, not decisions)
- **Code repositories and model pages count as classics:** llama.cpp, vLLM, OpenClaw, Codex CLI, Hugging Face model cards. So do a license page (CC BY 4.0) and news figures ("$852 billion valuation").
- **Titles from link words are still uneven:** "And, of course, this isn't really unique to computer architecture" (Joel Spolsky's Law of Leaky Abstractions), "I've previously shown". A page's real title needs a fetch.
- **"Cited again this week" holds 30 at the top,** so the view is mostly recent re-citations.
- **Two sources is a low bar:** many classics are one community passing a link around.

## Questions for the owner
- What did you expect to see in Classics, and what did you see instead?
- Is a classic something to *read* (essays, papers), or also tools, repos and datasets?
- Should Classics be a reading list (what to read next), or a map (what your sources keep standing on)?
- Is "cited again this week" useful at the top, or noise?

## Where the data is
- **The lab:** `insight_lab`, http://localhost:3100 → classics.
- **The measurements:** `plan/issues/0051-news-and-classics.md` ("Real data").
