# 0118 — Source track record: who was right, how early, and who only repeats

Status: **future** (2026-11-05, the owner). Mark X Stalker (`plan/INSIGHT_mark_x_stalker_plan.md`, feature 4). Recording may start during Stealth, as soon as its "a leak that came true" rule passes.

**Constraints:**
- Mark X's tables only; Mark IX unchanged;
- every number opens its evidence;
- no source is judged on too few cases;
- no real source names in committed files;
- keep everything.

## Why
- A rumor today looks the same from every source. INSIGHT can't say that one account's leaks about a lab came true 14 times and were wrong 3, or that another's are usually wrong.
- Stealth links a rumor to the release that confirmed it. Over months those links are each source's history, and no reader or aggregator keeps it, because none of them remember.
- It's a base for:
  - weighting rumors ("usually right about this lab");
  - ranking News earlier, when a story is broken by a reliable source;
  - noise per source (0093);
  - Discover by evidence ("this source broke 5 stories early that you saw later from others", 0101).

## What it records (per source, per topic: a lab, a product family, a field)
1. **Rumors:** confirmed, wrong and pending.
   - A rumor is wrong when the maker shipped something else, or the stated date passed by a margin with nothing shipped.
   - It stays pending otherwise, and pending never counts as wrong.
2. **Lead time:** days between the source's rumor or first report and the maker's own post.
3. **First or repeat:** how often it's the first to report a story (0064's tree) against posting in a story someone else broke. Copies are counted apart.
4. **Accurate details:** once confirmed, were its numbers right? For example, a rumored price against the real one (0095).
5. **Corrections:** its own later posts that correct or delete an earlier claim.

## Rules
- **A minimum count:** below it (proposed: 5 resolved rumors on a topic) the record shows "too few to tell" and never a rate.
- **Evidence:** each count opens its cases: the rumor post, the confirming or contradicting post, and the days between them.
- **Topic split:** a source can be reliable on one lab and useless on another, so no single overall score is shown alone.
- **The maker's own posts are the reference.** Two sources repeating each other don't confirm a rumor.

## Storage
- Rows: (source, topic entity, rumor post, outcome, resolving post, lead days, evidence, confidence, `valid_from`), in Mark X's connection tables.
- The outcome closes with `valid_to` when it changes from pending.
- Counts are computed from the rows, never stored apart.

## Measure before building
- **Rebuild history:** run Stealth's leak rule over the archive from July. How many rumors, and how many resolve (confirmed or wrong) within 90 days? How many sources reach the minimum count?
- **Outcome precision:** 100 resolved cases, two blind labellers plus a referee. Bar: ≥ 90% right; "wrong" ≥ 95%, because calling a source wrong is the costly error.
- **Lead time:** against the maker's post times, on 50 cases.
- **The owner's check:** the records of 10 sources the owner knows well. Do they match the owner's sense of them? Any surprise is opened case by case.

## Not in this issue
- Rumor odds and predictions (the owner, 2026-11-05: too far).
- Noise-per-source verdicts (0093), which read these records.
