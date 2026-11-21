# 0152 — Claims at read time: what each post says, stored once, each with its quote

Status: **spec** (2026-11-10). Fusion stage 3 (Claims), the base of Fusion. Storage, the task kind and the quote
check: buildable now, in Shadow, behind a switch. The guide `claims-v1` passed 0161 E2 (2026-11-10, see "Measured"): asked on its own, not with the reading. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: `plan/HANDOFF-v10.md`; 0086 (how a task kind and its guide are added; `translate` and `track` are small
examples); `markx/schemas.py`, `validate.py`, `tasks.py`; 0090 (mentions and identity); 0095, 0097, 0118 (what
Stalker wanted from claims).

**The owner (2026-11-10):** "you are right about to produce valuable information at start when post is read."

**Constraints:** Shadow (mx_* tables only; Mark IX only read); keep everything; no real names in committed files;
unit tests + 3–5 real checks; realdata-check once at release.

## Why (rough: private `plan/research/fusion/out/F2a`, `F2d`, `F4c`, `F4d`, `F8i`, `F8d`)
- The stored unit is the post. A timeline, a number over time, "what is new here" and a digest each have to re-read
  posts. In later posts of a story, **43% of claims had already been said** by an earlier post.
- Claims read by one guide held on a second, unrelated organisation: **19 of 20 right** with the guide unchanged.
- What did not hold, and shapes the fields below:
  - **a closed list of metrics:** a third of number facts fell outside it → the metric is free text, and a number
    carries its **basis**;
  - **dates:** 37 of 100 event dates were only the post's date → the event date is its own field, empty when the
    post does not give one;
  - **who says it:** a knowledge page built on claims was wrong mostly where a quoted person's words were stored as
    the source's own (46 of 62 lines supported) → **speaker** apart from the source.
- Cost: about $0.46 more per 1,000 posts (today: about $1.38).

## What it does
### 1. A claim
One row of `mx_claims` per thing a post asserts (at most 12 a post or window), from the task's answer:

| Field | What |
|---|---|
| `post_id`, `window`, `seq` | where it is |
| `text` | one English sentence, who did or said what |
| `quote` | the exact words of the post it rests on (the post's language) |
| `kind` | the happening's type (0151's list; today's until then) |
| `status` | official, reported, rumour, denied, opinion |
| `speaker` | who asserts it: the source itself, or a named person or organisation the post quotes or relays |
| `subject` | the entity it is about (a name; linked to a mention by identity, as mentions are) |
| `event_date`, `date_precision` | when the happening was or will be; null when the post gives none (never the post's date by default) |
| `number` | value, unit, `metric` (free text), `basis` (per year, year on year, cumulative, a forecast, …), `period`, `scope` (free text) — null for a claim with no number |
| `guide`, `call_id`, `valid_from`, `valid_to` | as every Mark X answer |

### 2. The quote check (by code, at validation)
- A claim is stored only if its `quote` is found in the post's text (after the same folding search uses: case,
  spaces, quote marks). A claim without its quote is refused and counted; the others of the answer are kept
  (0150 A).
- This is the one grounding rule every later view relies on: a line on any page opens the quote it came from.

### 3. The task
- Kind `claims`, guide `claims-v1`. Planned like `read`: newest first, the reading window, after `read` and
  `entities`; one call per long post's window (0150 C), several short unrelated posts per call.
- **Not asked** of posts whose reading says kind `other`, or under 20 words (today's rule A).
- E2 also decides **one call or two**: claims asked together with the reading (the post is sent once) against
  claims asked alone.

### 4. What reads claims
Nothing in this issue shows claims except one place, for checking: the post's Mark X panel lists its claims, each
with its quote marked in the text and ✓ / ✗ label buttons (the labels feed 0155's queue and E2's later rounds).
The views are 0153, 0156, 0157, 0158.

## What the results should be
- For every read post: its claims, each traceable to its words. Bars (E2): a claim is in its post 95%; subject,
  speaker and number fields right 90%; an event date, when given, right 90%.
- Refused for a missing quote: under 5% of claims.
- Stalker's numbers over time (0095) and the knowledge page (0156) become queries over `mx_claims`.

## Done when
- Migration; the schema, validation and the quote check (folded matching, a refused claim never sinks its
  answer); planning order; the fake-claude test; the panel's list with labels.
- On a local server copy: claims for the newest 500 read posts; claims per post, refused share, cost per 1,000.
- The switch is turned on for the server only when E2 passes and the owner says.

## Measured (E2, 2026-11-10; private: `plan/research/fusion/measure/E2/REPORT.md`)
147 unseen posts (AI news; Georgian and Caucasus news in three languages; climate and energy), read to 6,000
characters, 676 claims, checked by two Haiku checkers (all 676, and 276 of them again).

| | Result | Bar |
|---|---|---|
| Quote found in the post (code) | 676 of 678 | refused under 5%: met |
| The claim is what the post says | 96.0% (94–97) and 97.8% (95–99); none absent, 27 "partly" | 95%: met at the point |
| Speaker, subject | 99–100% | 90%: met |
| Number; its basis | 98%; 94–98% | 90%: met |
| Event date, when given | 91.3% (86–95) | 90%: met at the point |

- **One call or two (section 3): two.** Asked together with the reading, the guide gave half the claims (2.3 a post
  against 4.6; 15 posts with none) and 89% of them were what the post says.
- **For claims-v2** (a new set before it is scored): 41 claims left `event_date` empty though the post gave a year
  or a period for a number; a body's own statement relayed by an outlet was marked "reported" instead of
  "official".
- **Cost:** about $1.36 per 1,000 posts at 6,000 characters and 3 posts a call, not the $0.46 estimated above.
- **Not measured:** how much of a post its claims cover.

## Measured again (claims-v2, 2026-11-20; private: `plan/research/fusion/measure/x1120/C2/`)
New set of 150 posts (50 AI news, 100 from six other spheres); v1 and v2 (cap 12, dates for years and periods with `date_precision`, relayed official statements) on the same posts.
| | v1 | v2 |
|---|---|---|
| claims a post | 5.1 | 6.9 |
| claim is what the post says | 97.3% | 97.8% |
| basis | 92.3% | 94.9% |
| event date when given | 88.8% | 93.2% (90-95) |
| date misses | 5.4% | 2.1% |
**Adopt claims-v2.** Claims past the 8th: 76 of 79 right. For v3: a quarter form (`YYYY-Qn`: 20 of v2's 24 wrong dates); validation refuses status "source" (4 claims).

## Measured: from the stored reading? (2026-11-22; private: `plan/research/fusion/measure/x1122/CU/`)
On 50 AI posts: of claims-v2's 333 claims, the shipped reading (ent-v5) holds 22% fully, 52% partly, 26% not (number claims 45% fully). It never stores a quote, a per-claim speaker, status or subject, or a number's unit, basis, period and scope; one event date per post. **Claims stay a separate task** (this issue's section 3); the stored event headline and numbers may be passed to it as context.
