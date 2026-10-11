```meta
kind: principles
```

# Principles

The constitution of INSIGHT's design: every doc, prototype and decision cites these numbers, and changing one needs the owner. Each one's why, do and don't: [principles explained](system/principles-explained.md).

- **P1 Reading first.** The reader is home, and navigation lives in one top bar.
- **P2 Monochrome, dark by default.** Black and white only, like news.smol.ai; light is the same system inverted.
- **P3 Hierarchy from size, weight and space.** Three text tones and two border strengths carry all emphasis.
- **P4 Posts in one centred column.** A post reads in one centred measure of about 68ch, with nothing beside it.
- **P5 Icons for actions, words for places.** Actions on a post are icon-only (↗ ☆ ⧉) with a tooltip and a label; navigation is lowercase words.
- **P6 No metadata noise.** Show what helps you choose what to read: source, date, title.
- **P7 Fetching lives in Sources.** Reading views never fetch, ingest or hold secrets; jobs live in Sources and secrets only in Connections.
- **P8 One click to where it's managed.** Every source or track name in a reading view links to its place in Sources.
- **P9 One place per job.** Each job has exactly one page; a second view of the same thing is retired into the first.
- **P10 Retire it, keep the idea.** A surface that doesn't serve reading leaves `main`: its code goes to a git tag and its idea stays as an issue in `plan/issues`.
- **P11 Honest states.** Every state is a glyph plus a word, a stopped system says so out loud, and worst-case data is an acceptance gate.
- **P12 Calm motion, instant response.** What you do hundreds of times a day never animates; rare surfaces get one short ease-out; every press answers.

## How we change the design

1. **Prototype first:** a layout or flow change starts as a prototype; copy and spacing fixes go straight into the page and its doc together.
2. **Cite a principle:** every change cites a P-number; if none supports it, it isn't made, or the owner discusses the principle.
3. **Docs describe what is:** a page doc matches the shipped page; proposals live only in prototypes.
4. **Fixed template:** a page doc has the nine sections, Purpose to Open issues, in at most 150 lines.
5. **Size limits:** this page fits on one screen, one line per principle; at most 12.
6. **Coverage test:** `src/design/coverage.test.ts` fails on an unclaimed route, a page doc off its template, a state with no scenario, an unknown P-number, and this page over 40 lines or 450 words.
