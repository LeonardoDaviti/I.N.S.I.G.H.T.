```meta
kind: principles
```

# Principles

The constitution of INSIGHT's design. Every page doc, prototype and decision cites these numbers. Changing one needs the owner.

- **P1 Reading first.** The reader is home, and navigation lives in one top bar. *Why:* INSIGHT exists to read, and a page of links is navigation pretending to be content. *Do:* `/` opens the unread feed. *Don't:* a hub of cards that only link to other pages.
- **P2 Monochrome, dark by default.** Black and white only, like news.smol.ai; light is the same system inverted. *Why:* colour competes with the text and drifts page by page. *Do:* the inverted block for the one loudest thing. *Don't:* a hue, a gradient or a glow.
- **P3 Hierarchy from size, weight and space.** Three text tones and two border strengths carry all emphasis. *Why:* without colour, structure must come from type and whitespace. *Do:* an unread title at weight 600. *Don't:* blue links or a red error.
- **P4 Posts in one centred column.** A post reads in one centred measure of about 68ch, with nothing beside it. *Why:* the eye should never hunt for where the text starts. *Do:* the post page's single column. *Don't:* a notes panel competing with the article.
- **P5 Icons for actions, words for places.** Actions on a post are icon-only (↗ ☆ ⧉) with a tooltip and a label; navigation is lowercase words. *Why:* actions repeat on every post and words would outshout the title. *Do:* ↗ opens the original. *Don't:* an "Open original" button on every row.
- **P6 No metadata noise.** Show what helps you choose what to read: source, date, title. *Why:* machine detail is not reading. *Do:* `Simon Willison / Oct 10`. *Don't:* post counts, token estimates, model names, "via gemini".
- **P7 Fetching lives in Sources.** Reading views never fetch, ingest or hold secrets; jobs live in Sources and secrets only in Connections. *Why:* a reader that fetches mixes waiting with reading and leaks job failures into the page. *Do:* an empty scope points quietly to Sources. *Don't:* a "Fetch now" button in the reader.
- **P8 One click to where it's managed.** Every source or track name in a reading view links to its place in Sources. *Why:* removing a noisy source should not start with a search. *Do:* a track name opens `/settings/sources?track=<id>`. *Don't:* a source name as plain text.
- **P9 One place per job.** Each job has exactly one page; a second view of the same thing is retired into the first. *Why:* two components showing the same posts drift apart. *Do:* `/tracks/:id` redirects to the reader. *Don't:* a track page that copies the feed.
- **P10 Hide, don't delete.** Analysis surfaces are hidden behind `INSIGHT_ANALYSIS`, never removed, and come back unchanged. *Why:* the owner wants them later, as they were. *Do:* an off route redirects to the feed. *Don't:* delete a parked page's code.
- **P11 Honest states.** Every state is a glyph plus a word, a stopped system says so out loud, and worst-case data is an acceptance gate. *Why:* quiet grey text once hid ten days without ingestion. *Do:* "ingestion has stopped" instead of "all caught up". *Don't:* a colour-only dot, or a stale briefing above fresh posts.
- **P12 Calm motion, instant response.** What you do hundreds of times a day never animates; rare surfaces get one short ease-out; every press answers. *Why:* motion on frequent actions is latency. *Do:* j/k and ⌘K at 0ms. *Don't:* `transition: all`, or ignoring reduced motion.

## How we change the design

1. **Small changes:** a change to layout or flow starts as a prototype. Copy and spacing fixes go straight into the page and its page doc, in one commit.
2. **Cite a principle:** every change cites at least one P-number. If none supports it, it isn't made, or the owner discusses the principle.
3. **Docs describe what is:** a page doc matches the shipped page. Proposals live only in prototypes, never as prose in a doc.
4. **Fixed template:** a page doc has Purpose, Entry & URL, Anatomy, States, Interactions & keys, Worst cases, A11y & motion, Decisions and Open issues, in at most ~150 lines.
5. **Size limits:** this page fits on one screen; at most 12 principles.
6. **Coverage test:** `src/design/coverage.test.ts` fails when a route has no page, parked or redirect doc, when a page doc lacks its template or (from S3) a specimen for one of its states, and when a doc cites a principle that doesn't exist.
