"""The merge report (issue 0075 E): the cases, the invariants against main's baseline, the story job's
identity and the diff, from the two sides realdata-check.sh ran. Private: it names the owner's posts.

    python -m insight_core.checks.report --work <dir with base/ and head/> --out report.md
                                        [--label-base main --label-head <branch>] [--copy <db>] [--allow name=reason …]

Exits 1 when the change can't merge: a case marked pass fails, an invariant rose with no reason
named, or a side's step failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from insight_core.checks import diff


# What fails the check whatever main does (issue 0110: main's deploy start failed on the server copy too).
MUST_BE_ZERO = {"story.deploy_start", "story.dangling",
                "markx.ix_unchanged", "markx.after_run",   # 0086 Safety: Mark X never changes Mark IX, nor breaks its own rules
                "markx.api_during_run",                    # 0112 Decided 13: the API answers under 1 s while Mark X decides
                "markx.api_during_rebuild"}                # 0121 Decided 8: ... and during a first start's rebuild
# Of those, the ones that fail above zero even when the branch does better than main (0112 Decided 13: "failing it
# means don't merge"; main's in-API decision run may be slower still).
ZERO_EVEN_IF_FELL = {"markx.api_during_run", "markx.api_during_rebuild"}


def _load(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _found(side: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name in ("deploy.json", "invariants.json", "jobs.json"):
        data = _load(os.path.join(side, name)) or {"found": []}
        out.update({f["name"]: f for f in data["found"]})
    return out


def build(work: str, *, labels=("main", "branch"), copy: str = "", allowed: Dict[str, str] | None = None) -> (str, List[str]):
    allowed = allowed or {}
    base, head = os.path.join(work, "base"), os.path.join(work, "head")
    problems: List[str] = []
    lines = [f"# realdata-check: {labels[1]} against {labels[0]}", "",
             f"Run {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC on scratch copies of `{copy}`; each version's code over its own copy."]
    for side, label in ((base, labels[0]), (head, labels[1])):
        job = _load(os.path.join(side, "job.json"))
        if job:
            lines.append(f"- {label}: story job (full) {job.get('wall_seconds')} s, {job.get('posts')} posts, {job.get('stories')} stories, "
                         f"News {job.get('news')}, Classics {job.get('classics')}; clock {job.get('now')}.")
        for step in ("snapshot", "invariants", "cases", "jobs"):
            log = os.path.join(side, f"{step}.log")
            if step != "cases" and os.path.exists(log) and not os.path.exists(os.path.join(side, f"{step}.json")):
                problems.append(f"{label}: {step} produced nothing (see {step}.log)")

    # A. the cases
    cases_head, cases_base = _load(os.path.join(head, "cases.json")), _load(os.path.join(base, "cases.json"))
    lines += ["", "## A. The cases"]
    if cases_head:
        s = cases_head["summary"]
        lines.append(f"{labels[1]}: {s['cases']} cases, {s['pass']} pass, {s['fail']} fail, {s['error']} error, {s['not checked']} not checked.")
        if s["broken"]:
            problems.append("cases marked pass that fail: " + ", ".join(s["broken"]))
            lines.append("- **Marked pass, failing:** " + ", ".join(s["broken"]))
        if s["fixed"]:
            lines.append("- **Marked fail, passing now** (mark them pass, with `since`): " + ", ".join(s["fixed"]))
        unchecked = {k: v["not checked"] for k, v in s["kinds"].items() if v["not checked"]}
        lines.append("- Not checked, by kind: " + (", ".join(f"{k} {n}" for k, n in sorted(unchecked.items())) or "none"))
        if cases_base:
            was = {r["id"]: r["status"] for r in cases_base["results"]}
            moved = [(r["id"], was.get(r["id"]), r["status"]) for r in cases_head["results"] if was.get(r["id"]) != r["status"]]
            lines.append(f"- Against {labels[0]}: " + ("no case changes state" if not moved else
                         ", ".join(f"{i} {a} → {b}" for i, a, b in moved)))
        for r in cases_head["results"]:
            if r["status"] in ("fail", "error") and r["marked"] == "pass":
                lines += [f"  - `{r['id']}`:"] + [f"    - {d}" for d in r["details"]]
    else:
        lines.append("No cases run (no cases file).")

    # B. the invariants
    fb, fh = _found(base), _found(head)
    lines += ["", "## B. The invariants", "", f"| invariant | {labels[0]} | {labels[1]} | of | verdict |", "|---|---|---|---|---|"]
    for name in list(dict.fromkeys([*fb, *fh])):
        b, h = fb.get(name, {}), fh.get(name, {})
        bc, hc = b.get("count"), h.get("count")
        verdict = "ok"
        if hc is None or hc < 0:
            verdict = "not measured"
            if name in MUST_BE_ZERO and "the machine's load" in (h.get("note") or ""):
                # 0112 Decided 13: a gate not measured because the machine was loaded is no pass
                verdict = "**NOT MEASURED**"
                problems.append(f"{name}: not measured ({labels[1]}): {h['note']}")
        elif bc is not None and bc >= 0 and hc > bc:
            verdict = f"allowed: {allowed[name]}" if name in allowed else "**ROSE**"
            if name not in allowed:
                problems.append(f"invariant {name} rose {bc} -> {hc}")
        elif bc is not None and bc >= 0 and hc < bc:
            verdict = "fell"
        if name in MUST_BE_ZERO and hc and hc > 0 and (verdict == "ok" or (verdict == "fell" and name in ZERO_EVEN_IF_FELL)):
            # broken on main too: still no merge
            verdict = "**FAILS**"
            problems.append(f"{name}: {hc} ({labels[1]})")
        shown = lambda c: "-" if c is None else "n/a" if c < 0 else c   # noqa: E731
        lines.append(f"| `{name}` {h.get('what') or b.get('what', '')} | {shown(bc)} | {shown(hc)} | {h.get('of') or ''} | {verdict} |")
    lines += ["", f"Examples ({labels[1]}, up to 5 each):"]
    for name, h in fh.items():
        if h.get("count"):
            # A version's finding may hold no list here (main's markx.api_during_run under load put its seconds there).
            examples = h.get("examples") if isinstance(h.get("examples"), list) else []
            lines.append(f"- `{name}`: " + "; ".join(str(e) for e in examples) + (f" ({h['note']})" if h.get("note") else ""))

    # C. the diff
    before, after = _load(os.path.join(base, "snapshot.json")), _load(os.path.join(head, "snapshot.json"))
    lines += ["", "## C. The diff"]
    flagged = None
    if before and after:
        found = diff.compare(before, after)
        flagged = diff.needs_reading(found)
        text = diff.report(found, before, after, labels=labels)
        lines += ["", text.split("\n", 2)[2]]
        with open(os.path.join(work, "diff-counts.json"), "w", encoding="utf-8") as f:
            json.dump(diff.counts(found), f, indent=1)
    else:
        problems.append("a snapshot is missing: no diff")
        lines.append("No diff: a snapshot is missing.")

    # Lead changes to read (issue 0104): said under the verdict, never a failure on their own.
    reading = [] if flagged is None else [f"**Needs reading: {flagged}** News lead change{'s' if flagged != 1 else ''}"
                                          + (" (C. The diff, News, \"" + diff.NEEDS_READING + "\")." if flagged else "."), ""]
    lines[2:2] = ["", "**Verdict: " + ("FAIL**: " + "; ".join(problems) if problems else "PASS**"), "", *reading]
    return "\n".join(lines) + "\n", problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label-base", default="main")
    ap.add_argument("--label-head", default="branch")
    ap.add_argument("--copy", default="")
    ap.add_argument("--allow", nargs="*", default=[])
    args = ap.parse_args(argv)
    text, problems = build(args.work, labels=(args.label_base, args.label_head), copy=args.copy,
                           allowed=dict(a.split("=", 1) for a in args.allow))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("verdict:", "FAIL" if problems else "PASS")
    for line in text.splitlines()[:8]:
        if line.startswith("**Needs reading"):
            print(line.replace("**", ""))
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
