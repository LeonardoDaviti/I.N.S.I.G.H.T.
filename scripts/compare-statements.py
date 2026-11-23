#!/usr/bin/env python3
"""The post-deploy comparison (0279 C4): what the database and the API spent per hour before a deploy and after it.

GET only. `save` reads a running server's statements since its API process started (v10.42+:
/api/operations/db-statements?since=start, with `api_routes`) and, given --prom, each insight container's CPU
seconds per hour over the same window (Prometheus, cAdvisor); `compare` puts two saves side by side, per hour of
their own windows (a save one hour after the start against one taken a day later compares like with like).

    scripts/compare-statements.py save http://100.86.230.4:5173 --prom http://100.86.230.4:9090 > before.json
    ... deploy, let it run at least an hour with the worker on ...
    scripts/compare-statements.py save http://100.86.230.4:5173 --prom http://100.86.230.4:9090 > after.json
    scripts/compare-statements.py compare before.json after.json

A statement is matched by its pg_stat_statements id (the same text normalized); one in a single side is listed as
gone or new. Only the top statements and routes each side lists are seen (20 and 40); `total` is every statement.
Each API process keeps its own routes and start: run `save` twice when two answer, or read the `process` field.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def _hours(since: str, at: float) -> float:
    start = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
    return max((at - start) / 3600.0, 1e-6)


def save(base: str, prom: str | None) -> dict:
    at = time.time()
    got = _get(base.rstrip("/") + "/api/operations/db-statements?since=start")
    if not got.get("enabled", True) or "since" not in got:
        raise SystemExit(f"no statements since the API's start: {got.get('reason')}")
    out = {"at": datetime.fromtimestamp(at, timezone.utc).isoformat(), "server": base, "since": got["since"],
           "hours": _hours(got["since"], at), "process": got.get("process"), "total_ms": got.get("total_ms"),
           "calls": got.get("calls"), "statements": got.get("statements", []), "api_routes": got.get("api_routes", {})}
    routes = out["api_routes"]
    if routes.get("since"):
        out["routes_hours"] = _hours(routes["since"], at)
    if prom:
        window = max(60, int(out["hours"] * 3600))
        q = f'sum by (name)(increase(container_cpu_usage_seconds_total{{name=~"insight.*"}}[{window}s]))'
        res = _get(prom.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": at}))
        out["cpu_s"] = {r["metric"].get("name"): float(r["value"][1]) for r in res["data"]["result"]}
    return out


def _per_hour(side: dict):
    h = side["hours"]
    stm = {s["id"]: (s.get("total_ms", 0) / h, s.get("calls", 0) / h, s.get("statement", "")[:90])
           for s in side["statements"]}
    rh = side.get("routes_hours") or h
    routes = {r["route"]: (r["total_ms"] / rh, r["count"] / rh) for r in side["api_routes"].get("routes", [])}
    cpu = {k: v / h for k, v in (side.get("cpu_s") or {}).items()}
    return stm, routes, cpu


def compare(a: dict, b: dict) -> str:
    sa, ra, ca = _per_hour(a)
    sb, rb, cb = _per_hour(b)
    out = [f"before: {a['since']} .. {a['at']} ({a['hours']:.1f} h); after: {b['since']} .. {b['at']} ({b['hours']:.1f} h)",
           "", "| per hour | before | after | change |", "|---|---|---|---|"]

    def row(name, x, y, unit):
        ch = "" if x is None or y is None else (f"{100 * (y / x - 1):+.0f}%" if x else "new")
        f = lambda v: "-" if v is None else f"{v:,.1f} {unit}"   # noqa: E731
        out.append(f"| {name} | {f(x)} | {f(y)} | {ch} |")
    row("database statements, all", (a.get("total_ms") or 0) / a["hours"] / 1000, (b.get("total_ms") or 0) / b["hours"] / 1000, "s")
    for name in sorted(set(ca) | set(cb)):
        row(f"CPU {name}", ca.get(name), cb.get(name), "s")
    out += ["", "| statement (per hour) | before s | after s | before calls | after calls |", "|---|---|---|---|---|"]
    for sid in sorted(set(sa) | set(sb), key=lambda k: -max(sa.get(k, (0,))[0], sb.get(k, (0,))[0])):
        x, y = sa.get(sid), sb.get(sid)
        text = (x or y)[2].replace("|", "/")
        out.append(f"| `{text}` | {'gone' if x is None else f'{x[0] / 1000:,.1f}'} | "
                   f"{'gone' if y is None else f'{y[0] / 1000:,.1f}'} | {'' if x is None else f'{x[1]:,.0f}'} | "
                   f"{'' if y is None else f'{y[1]:,.0f}'} |")
    out += ["", "| API route (per hour) | before s | after s | before calls | after calls |", "|---|---|---|---|---|"]
    for r in sorted(set(ra) | set(rb), key=lambda k: -max(ra.get(k, (0,))[0], rb.get(k, (0,))[0])):
        x, y = ra.get(r), rb.get(r)
        out.append(f"| `{r}` | {'-' if x is None else f'{x[0] / 1000:,.1f}'} | {'-' if y is None else f'{y[0] / 1000:,.1f}'} | "
                   f"{'' if x is None else f'{x[1]:,.0f}'} | {'' if y is None else f'{y[1]:,.0f}'} |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "save":
        prom = argv[argv.index("--prom") + 1] if "--prom" in argv else None
        json.dump(save(argv[1], prom), sys.stdout, indent=1)
        return 0
    if len(argv) == 3 and argv[0] == "compare":
        with open(argv[1]) as fa, open(argv[2]) as fb:
            print(compare(json.load(fa), json.load(fb)))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
