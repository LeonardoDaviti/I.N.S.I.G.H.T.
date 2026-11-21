# 0259 — A family's versions are versions of one thing (v10.30)

Server entity page, 2026-11-21: one model family listed 24 versions: its real ones mixed with a video game of the same
name, speculative numbers, effort / settings variants listed as versions ("<name> 5.2 (max)", "<name> 5 Max"), a ratio
read as a version ("5:1") and a model id read as version 5 ("<maker>-<name>-5-1" is 5.1).

## Built

1. **Journeys walk `family_versions`** (`checks/journeys.py`; hard-set entries `{id, from: family_versions,
   family_name_like, why}` in the private hard-set file, never a name in code): for each family whose name or key
   matches, each row of the family page's versions is checked with the check's own rules (apart from names'): its
   mentions' stated maker agrees with the family's; its version string is a version (no ratio, no model id's first
   number); no setting word variant listed as a version of its own. Each wrong one is a row in the breakage format
   (`returned`, `said`, `cause`, `fix`).
2. **Version parsing** (`markx/names.py`, the module that owns it):
   - `not_a_version` / `clean(fields, name, versions)`: a ratio stated as the version is no version (in `parse`, in
     `Ent.hk`, in `identity.entity_for` before an entity is made). A name written as a model id whose last two numbers
     were read as version + variant is one version **only when its family states that version** (`versions`): without
     it the rule was right 1 of 2 on the server copy (an id's "12-6" is a shape).
   - `setting(variant, name, type)`: a model's variant that is a setting of its version: its words all effort /
     settings words, and either only the plain ones (low, high, xhigh, minimal) or written in brackets in the name.
     Plain max / ultra / medium are tiers as often (phones, chips, models) and stay rows.
3. **Family page** (`entity_views.family_versions`): a ratio row left out; each row's version as `clean` reads it (with
   the family's listed versions); a setting listed under its version's row (`settings`), when the family lists that
   version. Frontend: the settings shown after their version.

Switches: none added or changed. `families.split` stays OFF.

## Measured (the one read-only server copy of 2026-11-19; re-parsed in Python, nothing written)

10,849 family roots, 28,155 version rows.

| what | before | after |
|---|---|---|
| ratio version strings listed as versions | 5 | 0 |
| model ids read as version + variant | 2 | 1 (the one whose family lists the version fixed; the other is no version and is left) |
| setting-word variants listed as versions (the check's broad word list) | 229 rows, 108 families | 197 rows, 107 families |
| settings listed under their version | 0 | 35 (35 of 35 right, read by hand) |
| families whose versions' stated makers form 2+ groups | 645 (1,441 rows outside the top group) | unchanged |

The reported family on the copy (journeys walk): right 13 / wrong 10 before, right 14 / wrong 6 after; the 6 left are
plain tier-or-setting words and a "latest" alias. Its game-namesake rows state the model's maker or none, so no maker
rule sees them.

## Does it suggest `families.split`?

Of 12 sampled multi-maker families, 9 hold a real namesake among the versions (a split would be right), 3 do not (an
alias miss, a remake by another studio, accessories). That supports measuring v10.28's ask-each-pair split on a rolled
back run (0250 "To measure"), not switching it on: 3 of 12 would be wrong splits by maker alone, and the reported case is
not a maker problem at all (its namesake rows state the same maker or none).

## Left

- Plain max / ultra / medium / ultracode / latest variants (197 rows): settings or tiers by meaning; a Mark X question
  (ask), not a word rule.
- Namesake versions whose mentions state the family's maker or none (the reported game rows, speculative numbers): a
  meaning-level check of each version against the family (0250 #1 asks makers only).
- Code-prefix families (a letter prefix of model codes made a family): many of the 645.
- A model id fixed to its version is still its own row until the `family_version` repair merges it (its hk now equals).
- The shown name chose "<name>-5.2" over "<maker brand> <name> 5.2" (entity_repair.shown): not looked at.
- The journeys hard-set file needs a `family_versions` entry (private).
