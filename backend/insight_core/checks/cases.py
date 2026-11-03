"""The judged cases run (issue 0075 A): each case's `expect` is checked against what the pages show.

A case (case.schema.json): {id, kind, now: "pass" | "fail", since, why, note, expect: [assertion, …]}.
An assertion names a surface (`on`, surfaces.py), what to select there, a `path` into its answer and
one test (paths.OPS), e.g.

    {"on": "post", "post": "https://…", "path": "title", "equals": "…"}
    {"on": "stories", "together": ["https://…", {"source": "…", "title": "…"}], "via": "citation"}

A case passes when every assertion holds. A case without assertions, or of a kind the runner can't
check (layout, a deploy's order of events), is "not checked" and listed, never silently skipped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from insight_core.checks import paths, refs
from insight_core.checks.surfaces import SURFACES, Context, story_sets

STATES = ("pass", "fail")
# Kinds that need a browser, a process's start or a fetch: never checked here (issue 0075 A3 lists them).
UNCHECKED_KINDS = {
    "layout": "needs a browser at a width",
    "deploy": "needs a start of the API on an older stories setting",
    "ops": "needs the API's start or a fetch run",
    "source_doctor": "needs a failing fetch",
    "mark_x_target": "Mark X's target, not a rule of today",
}
OPS = tuple(paths.OPS) + (paths.COUNT_OP,)


@dataclass
class Result:
    case: Dict[str, Any]
    status: str                 # pass | fail | error | not checked
    details: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.case["id"]

    @property
    def marked(self) -> str:
        return self.case.get("now", "")

    @property
    def broken(self) -> bool:
        """Marked pass, and doesn't pass: the runner exits 1."""
        return self.marked == "pass" and self.status in ("fail", "error")

    @property
    def fixed(self) -> bool:
        """Marked fail, and passes now: to be marked pass (with `since`)."""
        return self.marked == "fail" and self.status == "pass"


def load(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"] if isinstance(data, dict) else data


def problems(case: Dict[str, Any]) -> List[str]:
    """What makes a case unreadable by the runner (the schema's rules), [] when none."""
    out = []
    for key in ("id", "kind", "now"):
        if not case.get(key):
            out.append(f"no {key}")
    if case.get("now") and case["now"] not in STATES:
        out.append(f"now must be pass or fail, not {case['now'][:40]!r}")
    expect = case.get("expect")
    if expect is not None:
        if not isinstance(expect, list) or not all(isinstance(a, dict) for a in expect):
            out.append("expect must be a list of assertions")
        else:
            for a in expect:
                out.extend(_assertion_problems(a))
    return out


def _assertion_problems(a: Dict[str, Any]) -> List[str]:
    on = a.get("on")
    if on == "stories":
        if not any(k in a for k in ("together", "apart", "roundup")):
            return ["a stories assertion needs together, apart or roundup"]
        return []
    if on not in SURFACES:
        return [f"unknown surface {on!r}"]
    ops = [k for k in a if k in OPS]
    if len(ops) != 1:
        return [f"an assertion on {on} needs one test of {', '.join(OPS)}"]
    return []


def _check_stories(ctx: Context, a: Dict[str, Any]) -> Tuple[bool, str]:
    if "roundup" in a:
        roundup = ctx.ids(a["roundup"])
        of = ctx.ids(a["of"])
        ctx.cur.execute("""SELECT 1 FROM story_mentions m JOIN story_posts sp ON sp.story_id = m.story_id
                           WHERE m.post_id = ANY(%s::uuid[]) AND sp.post_id = ANY(%s::uuid[]) LIMIT 1""", (roundup, of))
        held = ctx.cur.fetchone() is not None
        want = a.get("is", True)
        return held == want, f"roundup of its story: {held}"
    together = "together" in a
    groups = [ctx.ids(r) if not (isinstance(r, dict) and r.get("first")) else ctx.ids(r)[:1]
              for r in a["together" if together else "apart"]]
    ids = [i for g in groups for i in g]
    of = story_sets(ctx, ids)
    shared = set.intersection(*(of[i] for i in ids)) if ids else set()
    detail = "stories: " + "; ".join(f"{i[:8]}→{','.join(sorted(s))[:17] or 'none'}" for i, s in of.items())
    if not together:
        return not shared, detail
    if not shared:
        return False, detail
    if a.get("via"):
        ctx.cur.execute("SELECT DISTINCT parent_reason FROM story_posts WHERE story_id = ANY(%s::uuid[]) AND post_id = ANY(%s::uuid[])",
                        (list(shared), ids))
        reasons = {r[0] for r in ctx.cur.fetchall()}
        return a["via"] in reasons, f"{detail}; reasons {sorted(r or '' for r in reasons)}"
    return True, detail


def check(ctx: Context, a: Dict[str, Any]) -> Tuple[bool, str]:
    """One assertion: (holds, what was seen)."""
    if a["on"] == "stories":
        return _check_stories(ctx, a)
    value = paths.get(SURFACES[a["on"]](ctx, a), a.get("path"))
    op = next(k for k in a if k in OPS)
    operand = a[op]
    if op in ("has_post", "lacks_post"):
        operand = [ctx.ids(r) for r in (operand if isinstance(operand, list) else [operand])]
    ok, extra = paths.test(value, op, operand)
    return ok, f"{a['on']}.{a.get('path') or ''} {op} {paths.shown(a[op], 60)}: saw {paths.shown(value)}{' (' + extra + ')' if extra else ''}"


def run_case(ctx: Context, case: Dict[str, Any]) -> Result:
    bad = problems(case)
    if bad:
        return Result(case, "error", bad)
    if case["kind"] in UNCHECKED_KINDS and not case.get("expect"):
        return Result(case, "not checked", [UNCHECKED_KINDS[case["kind"]]])
    if not case.get("expect"):
        return Result(case, "not checked", [f"no expect: {case.get('why') or 'not written yet'}"])
    details, ok = [], True
    for a in case["expect"]:
        try:
            held, seen = check(ctx, a)
        except refs.RefError as e:
            held, seen = False, f"error: {e}"
        except Exception as e:   # noqa: BLE001 - a case that can't be asked is reported, never fatal
            ctx.cur.connection.rollback()
            return Result(case, "error", [f"{type(e).__name__}: {e}"])
        ok &= held
        details.append(("ok   " if held else "FAIL ") + seen)
    return Result(case, "pass" if ok else "fail", details)


def run(ctx: Context, cases: Iterable[Dict[str, Any]], only: Optional[List[str]] = None) -> List[Result]:
    return [run_case(ctx, c) for c in cases if not only or c["id"] in only]


def summary(results: List[Result]) -> Dict[str, Any]:
    by_kind: Dict[str, Dict[str, int]] = {}
    for r in results:
        k = by_kind.setdefault(r.case.get("kind", "?"), {"checked": 0, "not checked": 0})
        k["not checked" if r.status == "not checked" else "checked"] += 1
    return {
        "cases": len(results),
        "pass": sum(r.status == "pass" for r in results),
        "fail": sum(r.status == "fail" for r in results),
        "error": sum(r.status == "error" for r in results),
        "not checked": sum(r.status == "not checked" for r in results),
        "broken": [r.id for r in results if r.broken],
        "fixed": [r.id for r in results if r.fixed],
        "kinds": by_kind,
    }


def lines(results: List[Result], verbose: bool = False) -> List[str]:
    """One line a case (`marked → status  id  kind`), then what broke; the kinds not checked at the end."""
    out = []
    for r in results:
        flag = "BROKEN" if r.broken else "FIXED" if r.fixed else ""
        out.append(f"{r.status.upper():<11} (marked {r.marked or '?':<4}) {r.id}  [{r.case.get('kind')}] {flag}".rstrip())
        if verbose or r.broken or r.fixed or r.status == "error":
            out.extend(f"    {d}" for d in r.details)
    s = summary(results)
    out.append("")
    out.append(f"{s['cases']} cases: {s['pass']} pass, {s['fail']} fail, {s['error']} error, {s['not checked']} not checked")
    unchecked = {k: v["not checked"] for k, v in s["kinds"].items() if v["not checked"]}
    if unchecked:
        out.append("not checked, by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(unchecked.items())))
    if s["broken"]:
        out.append("marked pass, failing now: " + ", ".join(s["broken"]))
    if s["fixed"]:
        out.append("marked fail, passing now: " + ", ".join(s["fixed"]))
    return out
