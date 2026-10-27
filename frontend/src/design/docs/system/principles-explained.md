```meta
kind: system
```

# Principles explained

The why behind each rule in [Principles](../principles.md), with one thing to do and one not to. The rules themselves live only there; this page explains, it never adds a rule.

## P1 Reading first

The reader is home, and navigation lives in one top bar.

- *Why:* INSIGHT exists to read, and a page of links is navigation pretending to be content.
- *Do:* `/` opens the unread feed.
- *Don't:* a hub of cards that only link to other pages.

## P2 Monochrome, dark by default

Black and white only, like news.smol.ai; light is the same system inverted.

- *Why:* colour competes with the text and drifts page by page.
- *Do:* the inverted block for the one loudest thing.
- *Don't:* a hue, a gradient or a glow.

## P3 Hierarchy from size, weight and space

Three text tones and two border strengths carry all emphasis.

- *Why:* without colour, structure must come from type and whitespace.
- *Do:* an unread title at weight 600.
- *Don't:* blue links or a red error.

## P4 Posts in one centred column

A post reads in one centred measure of about 68ch, with nothing beside it.

- *Why:* the eye should never hunt for where the text starts.
- *Do:* the post page's single column.
- *Don't:* a notes panel competing with the article.

## P5 Icons for actions, words for places

Actions on a post are icon-only (↗ ☆ ⧉) with a tooltip and a label; navigation is lowercase words.

- *Why:* actions repeat on every post and words would outshout the title.
- *Do:* ↗ opens the original.
- *Don't:* an "Open original" button on every row.

## P6 No metadata noise

Show what helps you choose what to read: source, date, title.

- *Why:* machine detail is not reading.
- *Do:* `Simon Willison / Oct 10`.
- *Don't:* post counts, token estimates, model names, "via gemini".

## P7 Fetching lives in Sources

Reading views never start a fetch, ingest or hold secrets; jobs live in Sources and secrets only in Connections. The top bar may show that one is running, linking to Sources.

- *Why:* a reader that fetches mixes waiting with reading and leaks job failures into the page. A reader that can't tell anything is running leaves you guessing whether to act.
- *Do:* an empty scope points quietly to Sources; the top bar's quiet `fetching · 3 of 41` links to the job.
- *Don't:* a "Fetch now" button in the reader.

## P8 One click to where it's managed

A source or track name in a reading view links to its place in Sources; in a feed row and in a post's byline it reads the source, with `settings` beside it in the byline.

- *Why:* removing a noisy source should not start with a search.
- *Do:* a track name opens `/settings/sources?track=<id>`; a post's byline reads `source / settings` (decision 020); a feed row's source name opens `/read/source/<id>` (decision 022).
- *Don't:* a source name as plain text.

## P9 One place per job

Each job has exactly one page; a second view of the same thing is retired into the first.

- *Why:* two components showing the same posts drift apart.
- *Do:* `/tracks/:id` redirects to the reader.
- *Don't:* a track page that copies the feed.

## P10 Retire it, keep the idea

A surface that doesn't serve reading leaves `main`: its code goes to a git tag and its idea stays as an issue in `plan/issues`.

- *Why:* hidden code costs every build and change, and the owner wants better versions later, not the old ones back (decision 016).
- *Do:* an off route redirects to the feed, and what the owner liked is written down.
- *Don't:* a flag that never turns back on.

## P11 Honest states

Every state is a glyph plus a word, a stopped system says so out loud, and worst-case data is an acceptance gate.

- *Why:* quiet grey text once hid ten days without ingestion.
- *Do:* "ingestion has stopped" instead of "all caught up".
- *Don't:* a colour-only dot, or a stale briefing above fresh posts.

## P12 Calm motion, instant response

What you do hundreds of times a day never animates; rare surfaces get one short ease-out; every press answers.

- *Why:* motion on frequent actions is latency.
- *Do:* j/k and ⌘K at 0ms.
- *Don't:* `transition: all`, or ignoring reduced motion.
