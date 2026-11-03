"""What changed between two versions' snapshots of one copy (issue 0075 C): for each derived thing, how
many changed, by kind of change, with up to EXAMPLES random examples each (id, before -> after).

    python -m insight_core.checks.diff --before main.json --after branch.json [--out report.md] [--json counts.json]
                                       [--label-before main --label-after <branch>] [--seed 75]

The examples hold the owner's data: the report goes to plan/research/lab/checks/ (private). The hand
checks of a change are drawn from it, across its kinds of change (0075 C2), not only the one it targets.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

EXAMPLES = 20
_ADDRESS = re.compile(r"(?:https?://\S+|(?:[\w-]+\.)+[a-zA-Z]{2,}/\S*)")

Change = Tuple[str, Any, Any]           # (id, before, after)
Changes = Dict[str, List[Change]]       # kind of change -> the changes


def _title_kind(a: str, b: str) -> str:
    if not b.strip():
        return "became empty"
    if not a.strip():
        return "was empty"
    if bool(_ADDRESS.search(a)) != bool(_ADDRESS.search(b)):
        return "an address left" if _ADDRESS.search(a) else "an address came"
    if b.rstrip("…").startswith(a.rstrip("…").rstrip()) or len(b) > len(a) and a.rstrip("…") in b:
        return "runs on (longer)"
    if a.rstrip("…").startswith(b.rstrip("…").rstrip()) or len(b) < len(a) and b.rstrip("…") in a:
        return "cut (shorter)"
    return "other words"


def _text_kind(a: str, b: str) -> str:
    if not b.strip():
        return "became empty"
    if not a.strip():
        return "was empty"
    if b in a:
        return "starts later"
    if a in b:
        return "starts earlier"
    return "other start"


def _by_value(before: Dict[str, Any], after: Dict[str, Any], kind: Callable[[Any, Any], str]) -> Changes:
    out: Changes = defaultdict(list)
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        if a is None and b is not None:
            out["new"].append((key, None, b))
        elif b is None and a is not None:
            out["gone"].append((key, a, None))
        elif a != b:
            out[kind(a, b)].append((key, a, b))
    return out


def titles(a: Dict, b: Dict) -> Changes:
    return _by_value({k: v["title"] for k, v in a.items()}, {k: v["title"] for k, v in b.items()}, _title_kind)


def texts(a: Dict, b: Dict) -> Changes:
    return _by_value({k: v["text"] for k, v in a.items()}, {k: v["text"] for k, v in b.items()}, _text_kind)


def links(a: Dict, b: Dict) -> Changes:
    pick = lambda d: {k: (v or {}).get("title") for k, v in d.items()}   # noqa: E731
    return _by_value(pick(a), pick(b), lambda x, y: "title changed")


def _groups(member: Dict[str, List]) -> Dict[str, frozenset]:
    stories: Dict[str, set] = defaultdict(set)
    for pid, rows in member.items():
        for row in rows:
            stories[row[0]].add(pid)
    return {sid: frozenset(p) for sid, p in stories.items()}


def membership(a: Dict, b: Dict) -> Changes:
    """Story membership: a post joined or left a story (in one version only), a story split or merged
    (its posts in 2+ stories of the other), or kept its core and gained or lost posts."""
    out: Changes = defaultdict(list)
    ga, gb = _groups(a["member"]), _groups(b["member"])
    in_a = {p: sid for sid, ps in ga.items() for p in ps}
    in_b = {p: sid for sid, ps in gb.items() for p in ps}
    for p in sorted(set(in_a) | set(in_b)):
        if p not in in_a:
            out["joined a story"].append((p, None, len(gb[in_b[p]])))
        elif p not in in_b:
            out["left every story"].append((p, len(ga[in_a[p]]), None))
    for sid, posts in sorted(ga.items()):
        targets = {in_b[p] for p in posts if p in in_b}
        if len(targets) >= 2:
            out["split"].append((sid, len(posts), sorted(len(gb[t] & posts) for t in targets)))
        elif len(targets) == 1:
            t = next(iter(targets))
            if gb[t] != posts and not any(ga.get(in_a.get(p)) is not None and in_a[p] != sid for p in gb[t] if p in in_a):
                out["gained or lost posts"].append((sid, len(posts), len(gb[t])))
    for sid, posts in sorted(gb.items()):
        sources = {in_a[p] for p in posts if p in in_a}
        if len(sources) >= 2:
            out["merged"].append((sid, sorted(len(ga[s] & posts) for s in sources), len(posts)))
    roles = {}
    for p in set(a["member"]) & set(b["member"]):
        ra = sorted((r[1], r[2] or "") for r in a["member"][p])
        rb = sorted((r[1], r[2] or "") for r in b["member"][p])
        if ra != rb:
            roles[p] = (ra, rb)
    for p, (ra, rb) in sorted(roles.items()):
        out["role or parent reason"].append((p, ra, rb))
    return out


def roundups(a: Dict, b: Dict) -> Changes:
    """A post that is a roundup (story_mentions) of a story in one version and not the other, stories
    matched by their posts."""
    ga, gb = _groups(a["member"]), _groups(b["member"])
    key_a = lambda sid: ga.get(sid, frozenset())   # noqa: E731
    key_b = lambda sid: gb.get(sid, frozenset())   # noqa: E731
    out: Changes = defaultdict(list)
    for p in sorted(set(a["mentions"]) | set(b["mentions"])):
        sa = {key_a(s) for s in a["mentions"].get(p, [])}
        sb = {key_b(s) for s in b["mentions"].get(p, [])}
        if sa != sb:
            kind = "became a roundup" if not sa else "no longer a roundup" if not sb else "a roundup of other stories"
            out[kind].append((p, len(sa), len(sb)))
    return out


def origins(a: Dict, b: Dict) -> Changes:
    ga, gb = _groups(a["member"]), _groups(b["member"])
    by_a = {ps: a["stories"].get(s, {}) for s, ps in ga.items()}
    by_b = {ps: b["stories"].get(s, {}) for s, ps in gb.items()}
    out: Changes = defaultdict(list)
    for ps in sorted(by_a.keys() & by_b.keys(), key=lambda x: sorted(x)):
        x, y = by_a[ps], by_b[ps]
        sid = sorted(ps)[0]
        if x.get("origin") != y.get("origin"):
            out["origin changed"].append((sid, x.get("origin"), y.get("origin")))
        elif x.get("origin_title") != y.get("origin_title"):
            out["origin title changed"].append((sid, x.get("origin_title"), y.get("origin_title")))
        if x.get("voices") != y.get("voices"):
            out["voices changed"].append((sid, x.get("voices"), y.get("voices")))
    return out


def news(a: Dict, b: Dict) -> Changes:
    ra = {r["lead"]: r for r in a["rows"]}
    rb = {r["lead"]: r for r in b["rows"]}
    out: Changes = defaultdict(list)
    for lead in sorted(set(ra) | set(rb)):
        x, y = ra.get(lead), rb.get(lead)
        if x is None:
            out["new row"].append((lead, None, f"{y['title']!r}, {len(y['posts'])} posts"))
        elif y is None:
            out["gone row"].append((lead, f"{x['title']!r}, {len(x['posts'])} posts", None))
        else:
            if x["posts"] != y["posts"]:
                out["posts changed"].append((lead, len(x["posts"]), len(y["posts"])))
            if x["voices"] != y["voices"]:
                out["voices changed"].append((lead, x["voices"], y["voices"]))
            if (x["first_at"], x["first"]) != (y["first_at"], y["first"]):
                out["first changed"].append((lead, x["first_at"], y["first_at"]))
            if x["title"] != y["title"]:
                out["title changed"].append((lead, x["title"], y["title"]))
    return out


def classics(a: Dict, b: Dict) -> Changes:
    out = _by_value(a["table"], b["table"], lambda x, y: "row changed")
    rows = out.pop("row changed", [])
    for url, x, y in rows:
        fields = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
        for field in fields:
            out[f"stored {field} changed"].append((url, x.get(field), y.get(field)))
    pa = {c["url"]: c["title"] for c in a["page"]}
    pb = {c["url"]: c["title"] for c in b["page"]}
    for url in sorted(pa.keys() & pb.keys()):
        if pa[url] != pb[url]:
            out["the page's title changed"].append((url, pa[url], pb[url]))
    return out


def discover(a: Dict, b: Dict) -> Changes:
    ra = {s["key"]: (i, s) for i, s in enumerate(a["suggestions"], 1)}
    rb = {s["key"]: (i, s) for i, s in enumerate(b["suggestions"], 1)}
    out: Changes = defaultdict(list)
    for key in sorted(set(ra) | set(rb)):
        if key not in ra:
            out["new suggestion"].append((key, None, rb[key][0]))
        elif key not in rb:
            out["gone suggestion"].append((key, ra[key][0], None))
        else:
            (i, x), (j, y) = ra[key], rb[key]
            if i != j:
                out["moved"].append((key, i, j))
            if x["voices"] != y["voices"]:
                out["voices changed"].append((key, x["voices"], y["voices"]))
            if x["names"] != y["names"]:
                out["names changed"].append((key, x["names"][:4], y["names"][:4]))
    return out


# derived thing -> (part, how to compare)
THINGS: List[Tuple[str, str, Callable[[Dict, Dict], Changes]]] = [
    ("titles", "posts", titles), ("text starts", "posts", texts), ("link titles", "links", links),
    ("roundups", "stories", roundups), ("story membership", "stories", membership), ("story origins", "stories", origins),
    ("News", "news", news), ("Classics", "classics", classics), ("Discover", "discover", discover),
]


def compare(before: Dict, after: Dict) -> Dict[str, Optional[Changes]]:
    out: Dict[str, Optional[Changes]] = {}
    for name, part, how in THINGS:
        a, b = before["parts"].get(part), after["parts"].get(part)
        out[name] = None if a is None or b is None else how(a, b)
    return out


def counts(found: Dict[str, Optional[Changes]]) -> Dict[str, Any]:
    return {name: None if ch is None else {"changed": sum(len(v) for v in ch.values()), **{k: len(v) for k, v in ch.items()}}
            for name, ch in found.items()}


def _cell(x: Any) -> str:
    text = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str)
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= 160 else text[:159] + "…"


def report(found: Dict[str, Optional[Changes]], before: Dict, after: Dict, *, labels=("before", "after"), seed: int = 75) -> str:
    rng = random.Random(seed)
    lines = [f"# realdata-diff: {labels[0]} → {labels[1]}", "",
             f"Clock: {before.get('now')} (both). Parts missing: {labels[0]} {before.get('missing') or 'none'}, "
             f"{labels[1]} {after.get('missing') or 'none'}.", "", "| derived thing | changed | by kind |", "|---|---|---|"]
    for name, ch in found.items():
        if ch is None:
            lines.append(f"| {name} | not compared | a snapshot lacks it |")
            continue
        total = sum(len(v) for v in ch.values())
        kinds = ", ".join(f"{k} {len(v)}" for k, v in sorted(ch.items(), key=lambda kv: -len(kv[1])))
        lines.append(f"| {name} | {total} | {kinds or '-'} |")
    for name, ch in found.items():
        if not ch:
            continue
        lines += ["", f"## {name}"]
        for kind, changes in sorted(ch.items(), key=lambda kv: -len(kv[1])):
            shown = rng.sample(changes, EXAMPLES) if len(changes) > EXAMPLES else changes
            lines += ["", f"### {kind} ({len(changes)}{', 20 at random' if len(changes) > EXAMPLES else ''})", "",
                      f"| id | {labels[0]} | {labels[1]} |", "|---|---|---|"]
            lines += [f"| {_cell(i)} | {_cell(x)} | {_cell(y)} |" for i, x, y in shown]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out")
    ap.add_argument("--json")
    ap.add_argument("--label-before", default="before")
    ap.add_argument("--label-after", default="after")
    ap.add_argument("--seed", type=int, default=75)
    args = ap.parse_args(argv)
    with open(args.before, encoding="utf-8") as f:
        before = json.load(f)
    with open(args.after, encoding="utf-8") as f:
        after = json.load(f)
    found = compare(before, after)
    summary = counts(found)
    for name, c in summary.items():
        print(f"{name:<18} " + ("not compared" if c is None else f"{c['changed']:>6} changed" +
                                ("  (" + ", ".join(f"{k} {n}" for k, n in c.items() if k != "changed") + ")" if c["changed"] else "")))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report(found, before, after, labels=(args.label_before, args.label_after), seed=args.seed))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
