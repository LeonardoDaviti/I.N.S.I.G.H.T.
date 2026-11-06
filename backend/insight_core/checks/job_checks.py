"""The invariants that run the story job (issue 0075 B, "Stories"), so they only ever get a scratch copy
(job.scratch_only), after a full rebuild.

    python -m insight_core.checks.job_checks --db <scratch dsn> [--now ISO] [--identity module:function] [--json out]

- `story.rebuild_identity` and `story.id_changes`: a second full rebuild with no new posts writes the
  same rows (table_rows), and no story's id changes.
- `story.identity`: the incremental job equals a full rebuild, row by row (0072 A's oracle). That check
  belongs to the incremental job (`insight_core.scripts.story_identity.check`, its own slice); this
  calls it, pluggable by `--identity`, as `fn(db_url, clock=now)` -> {"same", "tables": {name: {"differing",
  "only_first", "only_second", "rows"}}}. On a version without it the invariant is "not measured", with
  a note saying so, never a silent pass.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from insight_core.checks import table_rows
from insight_core.checks.invariants import EXAMPLES, Found
from insight_core.checks.job import run_full, scratch_only
from insight_core.checks.session import copy_now, open_copy

IDENTITY = "insight_core.scripts.story_identity:check"


def rebuild_twice(db_url: str, now: datetime) -> List[Found]:
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        first = table_rows.read_tables(cur)
        started = time.monotonic()
        run_full(db_url, now)
        again = table_rows.read_tables(cur)
    seconds = round(time.monotonic() - started, 1)
    of = sum(len(rows) for rows in first.values())
    a, b = table_rows.story_ids(first), table_rows.story_ids(again)
    moved = sorted(f"{a[m]} -> {b[m]}" for m in a.keys() & b.keys() if a[m] != b[m])
    counts = table_rows.by_table(first, again)
    return [
        Found("story.rebuild_identity", "stories", "rows a second full rebuild with no new posts writes differently",
              sum(counts.values()), of, [f"{t}: -{x} +{y}" for t, (x, y) in table_rows.differences(first, again).items()][:EXAMPLES],
              seconds, note=json.dumps({"by_table": counts}) if counts else ""),
        Found("story.id_changes", "stories", "a story whose id changes in a rebuild with no new posts", len(moved), len(a), moved[:EXAMPLES]),
    ]


def _identity_function(spec: str) -> Optional[Callable[..., Dict[str, Any]]]:
    module, _, name = spec.partition(":")
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        return None


def incremental_identity(db_url: str, now: datetime, spec: str = IDENTITY) -> Found:
    what = "rows the incremental job writes unlike a full rebuild (the incremental job's own check)"
    check = _identity_function(spec)
    if check is None:
        return Found("story.identity", "stories", what, -1, 0,
                     note=f"not measured: {spec} is not in this version (the incremental job brings it)")
    started = time.monotonic()
    result = check(db_url, clock=now)
    tables = result.get("tables", {})
    differing = {t: v.get("differing", 0) for t, v in tables.items() if v.get("differing")}
    examples = [f"{t}: -{v.get('only_first', [])[:1]} +{v.get('only_second', [])[:1]}" for t, v in tables.items() if v.get("differing")]
    return Found("story.identity", "stories", what, sum(differing.values()), sum(v.get("rows", 0) for v in tables.values()),
                 examples[:EXAMPLES], round(time.monotonic() - started, 1), note=json.dumps({"by_table": differing, "same": result.get("same")}))


def table_checksums(cur: Any) -> Dict[str, tuple]:
    """{table: (rows, md5 of its rows' md5s)} of every table but Mark X's mx_* (0079's per-table checksum)."""
    from psycopg import sql
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' "
                "AND relname NOT LIKE 'mx\\_%' ORDER BY 1")
    out = {}
    for (table,) in cur.fetchall():
        cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                            "FROM (SELECT md5(x::text) h FROM {} x) s").format(sql.Identifier(table)))
        out[table] = tuple(cur.fetchone())
    return out


def _mx_rows(cur: Any) -> int:
    cur.execute("SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace AND relkind = 'r' "
                "AND relname LIKE 'mx\\_%'")
    total = 0
    for (table,) in cur.fetchall():
        cur.execute(f"SELECT count(*) FROM {table}")
        total += cur.fetchone()[0]
    return total


def markx_unchanged(db_url: str, now: datetime) -> List[Found]:
    """0086 Safety 1: Mark IX's tables are the same with Mark X on and off. With Mark X off the scheduler runs nothing
    (no mx_* row is written); then two decision runs with it on (the second must find the first's work done) leave every
    table but mx_* row for row as it was. After the runs, the read-only Mark X invariants hold on what they wrote."""
    import os
    what = "Mark IX's tables (every table but mx_*) two decision runs with Mark X on change, or a run with it off"
    try:
        from insight_core.markx import decide
    except ImportError:
        return [Found("markx.ix_unchanged", "mark x", what, -1, 0, note="not measured: this version has no decision job")]
    from insight_core.checks import invariants
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        before, mx_before = table_checksums(cur), _mx_rows(cur)
    old = os.environ.get("INSIGHT_MARKX")
    started = time.monotonic()
    try:
        os.environ["INSIGHT_MARKX"] = "off"
        try:   # 0112 Decided 10: insight-ingestion's runner (markx/jobs.py); a version before has decide.Scheduler
            from insight_core.markx.jobs import Runner
            off = Runner(db_url, spawn=False).tick()
        except ImportError:
            off = decide.Scheduler(debounce=None, every=None).run_now()
        with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
            off_rows = _mx_rows(cur) - mx_before
        os.environ["INSIGHT_MARKX"] = "on"
        runs = []
        for _ in range(2):
            with open_copy(db_url, writable=True) as conn, conn.cursor() as cur, conn.transaction():
                runs.append(decide.run(cur, now=now))
    finally:
        if old is None:
            os.environ.pop("INSIGHT_MARKX", None)
        else:
            os.environ["INSIGHT_MARKX"] = old
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        after = table_checksums(cur)
        run = invariants.Run(db_url, cur, now)
        # as run_all asks them: an invariant this version's schema can't answer (the checks package is the head's,
        # run over the base's code too: 0119's mx_entity* tables on main) is not measured, never a failed job check
        mx = [f for f in invariants.run_all(run, only=[i.name for i in invariants.INVARIANTS
                                                       if i.name.startswith("markx.")]) if f.count >= 0]
    seconds = round(time.monotonic() - started, 1)
    changed = sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))
    first, second = runs
    note = {"off": {"ran": off is not None, "mx_rows_written": off_rows},
            "first_run": {k: first.get(k) for k in ("stories", "posts", "questions", "answered", "changes", "news", "tasks_added")},
            "second_run": {"memberships": second.get("memberships"), "news_written": (second.get("news") or {}).get("written"),
                           "tasks_added": second.get("tasks_added")}}
    out = [Found("markx.ix_unchanged", "mark x", what, len(changed) + (1 if off_rows else 0) + (1 if off is not None else 0),
                 len(before), [f"{t}: {before.get(t)} -> {after.get(t)}" for t in changed][:EXAMPLES],
                 seconds, note=json.dumps(note, default=str))]
    out.append(Found("markx.after_run", "mark x", "the Mark X invariants on what the decision runs wrote (2-5, summed)",
                     sum(f.count for f in mx), sum(f.of for f in mx), [f"{f.name}: {e}" for f in mx for e in f.examples][:EXAMPLES],
                     note=json.dumps({f.name: f.count for f in mx})))
    return out


SLOW_MS = 1000
PROBES = ("/api/version", "/api/feed?limit=20")
BASELINE_S = 10.0   # the probes' window before the run, and again after it: the machine's own slowness
QUIET = 0.1         # a window with no run is quiet when at most this share of its requests is slow or fails
QUIET_WAIT_S = 600  # how long the run waits for a quiet window before the invariant is not measured
LOADED_NOTE = "not measured: the API was slow with no run (the machine's load); rerun the check when it is quieter"


def quiet(window: List[Dict[str, Any]]) -> bool:
    """A window of probes with no run in it is quiet enough to measure a run against: some answers, at most QUIET of
    them slow. A loaded one (most slow) can't show what a run adds."""
    return bool(window) and sum(map(_slow, window)) <= QUIET * len(window)


def _slow(row: Dict[str, Any]) -> bool:
    return row["ms"] >= SLOW_MS or row["status"] != 200


def added_by_run(before: List[Dict[str, Any]], during: List[Dict[str, Any]],
                 after: List[Dict[str, Any]]) -> "tuple[int, Dict[str, Any]]":
    """The slow or failing requests the run adds: those during it, less what the same probes' rate before and after it
    (the API with no run, on the same machine at the same time) predicts for as many requests. The check shares the
    machine and its database with other checks, and the API's routes read the database on their event loop, so a busy
    database slows even /api/version: that slowness is the machine's, not the run's. With no slow request before or
    after (a quiet machine) every slow one during the run counts, as the rule says."""
    base = before + after
    rate = sum(map(_slow, base)) / len(base) if base else 0.0
    expected = round(rate * len(during))
    slow = sum(map(_slow, during))
    return max(0, slow - expected), {"slow_during": slow, "expected": expected, "baseline_rate": round(rate, 3),
                                     "before": f"{sum(map(_slow, before))} of {len(before)}",
                                     "after": f"{sum(map(_slow, after))} of {len(after)}"}


def _api_workers(app_dir: str) -> int:
    """The number of API processes the version's start script runs (docker/start-backend.sh), 1 when it says none."""
    import re
    try:
        text = open(os.path.join(app_dir, "docker", "start-backend.sh"), encoding="utf-8").read()
    except OSError:
        return 1
    found = re.search(r"API_WORKERS:-(\d+)", text) or re.search(r"--workers\s+(\d+)", text)
    return int(found.group(1)) if found else 1


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Api:
    """The version's API on the copy (as many processes as its start script runs, Mark X on, its start work left to
    the measured work as the supervisor leaves it) and its probes: /api/version and /api/feed every 0.5 s, each of
    the window it was asked in (before, during, after)."""

    def __init__(self, db_url: str, log_name: str) -> None:
        import subprocess
        self.app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.workers, port = _api_workers(self.app_dir), _free_port()
        self.base = f"http://127.0.0.1:{port}"
        self.env = {**os.environ, "DATABASE_URL": db_url, "INSIGHT_MARKX": "on", "INSIGHT_API_SUPERVISED": "1",
                    "PYTHONPATH": self.app_dir, "PYTHONDONTWRITEBYTECODE": "1"}
        self.log_name = log_name
        self.log = open(log_name, "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--app-dir", self.app_dir, "--host",
                                      "127.0.0.1", "--port", str(port), "--workers", str(self.workers)], env=self.env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        self.rows: List[Dict[str, Any]] = []
        self.phase = ["before"]
        self.asked: Dict[str, int] = {}
        self.lock = __import__("threading").Lock()
        self.stop = __import__("threading").Event()

    def get(self, path: str, timeout: float = 10.0) -> Dict[str, Any]:
        import urllib.request
        t = time.monotonic()
        status = 0
        try:
            with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
                r.read()
                status = r.status
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "code", -1) or -1
        return {"path": path.split("?")[0], "ms": round((time.monotonic() - t) * 1000), "status": status}

    def _ask(self, path: str, window: str) -> None:
        self.rows.append({**self.get(path), "phase": window})

    def probe(self) -> None:
        import threading
        pending: List[threading.Thread] = []
        while not self.stop.is_set():
            for path in PROBES:
                with self.lock:
                    self.asked[self.phase[0]] = self.asked.get(self.phase[0], 0) + 1
                th = threading.Thread(target=self._ask, args=(path, self.phase[0]), daemon=True)
                th.start()
                pending.append(th)
            self.stop.wait(0.5)
        for th in pending:
            th.join(12)

    def answered(self, window: str) -> List[Dict[str, Any]]:
        """The window's requests, once every one asked in it is answered or timed out (at most the 10 s timeout)."""
        end = time.monotonic() + 12
        while time.monotonic() < end and sum(1 for r in self.rows if r["phase"] == window) < self.asked.get(window, 0):
            time.sleep(0.2)
        return [r for r in self.rows if r["phase"] == window]

    def close(self) -> None:
        import subprocess
        self.stop.set()
        self.proc.terminate()
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def _measured(db_url: str, name: str, what: str, log_name: str, work: Callable[["_Api"], Dict[str, Any]]) -> Found:
    """0112 Decided 13's measure, for any `work`: the API starts; the probes run; `work(api)` starts only after a quiet
    10 s window (at most 1 request in 10 slow or failing; loaded windows are set aside, 20 s apart, for at most
    QUIET_WAIT_S, then the invariant is NOT MEASURED); after it, a 5 s tail and 10 s more of probes. Each request
    slower than 1 s, or failing, during the work counts, less the rate the same probes show before and after it
    (added_by_run): what is measured is the work's slowdown, not the machine's load. `work` returns its notes."""
    import threading
    started = time.monotonic()
    api = _Api(db_url, log_name)
    run_seconds, note_extra = None, {}
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and api.get("/api/version", 2)["status"] != 200:
            if api.proc.poll() is not None:
                return Found(name, "mark x", what, 1, 0, note=f"the API did not start ({log_name})")
            time.sleep(1)
        prober = threading.Thread(target=api.probe, daemon=True)
        prober.start()
        waited, loaded = time.monotonic() + QUIET_WAIT_S, []
        while True:   # the work starts after a quiet 10 s window; the loaded ones before it are set aside
            api.stop.wait(BASELINE_S)
            api.phase[0] = "aside"          # asked while the window is judged: no window's
            window = api.answered("before")
            if quiet(window):
                break
            loaded.append(f"{sum(map(_slow, window))} of {len(window)}")
            for r in window:
                r["phase"] = "loaded"
            api.asked.pop("before", None)
            if time.monotonic() > waited:
                return Found(name, "mark x", what, -1, 0, [], round(time.monotonic() - started, 1),
                             note=f"{LOADED_NOTE} (slow in each 10 s window over {QUIET_WAIT_S} s: {', '.join(loaded)})")
            api.stop.wait(20)
            api.phase[0] = "before"
        note_extra["loaded_windows_before"] = loaded
        api.phase[0] = "during"
        t0 = time.monotonic()
        note_extra.update(work(api) or {})
        run_seconds = round(time.monotonic() - t0, 1)
        api.stop.wait(5)
        api.phase[0] = "after"
        api.stop.wait(BASELINE_S)
    finally:
        api.close()
    windows = {w: [r for r in api.rows if r["phase"] == w] for w in ("before", "during", "after")}
    count, added = added_by_run(windows["before"], windows["during"], windows["after"])
    by_path = {}
    for w, of in windows.items():
        for path in sorted({r["path"] for r in of}):
            ms = sorted(r["ms"] for r in of if r["path"] == path)
            by_path.setdefault(w, {})[path] = {"n": len(ms), "p50": ms[len(ms) // 2],
                                                "p95": ms[min(len(ms) - 1, int(len(ms) * .95))], "max": ms[-1]}
    worst = sorted((r for r in windows["during"] if _slow(r)), key=lambda r: -r["ms"])[:EXAMPLES]
    return Found(name, "mark x", what, count, len(windows["during"]),
                 [f"{r['path']} {r['ms']} ms (status {r['status']})" for r in worst], round(time.monotonic() - started, 1),
                 note=json.dumps({"api_processes": api.workers, "run_seconds": run_seconds, **added,
                                  "paths": by_path, **note_extra}, default=str))


def api_during_run(db_url: str, now: datetime) -> Found:
    """0112 Decided 13: the reader's API answers while Mark X decides. The version's API (as many processes as its
    start script runs, Mark X on) serves the copy; a full decision run with the entity-candidate flush happens where
    the version runs it (insight-ingestion's job in a process of its own, or, before 0112 Decided 10, inside the API:
    its start's run and POST /api/markx/decide); meanwhile /api/version and /api/feed are asked every 0.5 s. Each
    request slower than 1 s, or failing, counts, less the rate the same probes show for 10 s before the run and 10 s
    after it (added_by_run): what is measured is the run's slowdown, not the machine's load."""
    import importlib.util
    import subprocess
    import urllib.request
    what = ("API requests (/api/version, /api/feed) slower than 1 s or failing while a decision run and the candidate flush run, "
            "over the rate before and after it")
    try:
        from insight_core.markx import decide  # noqa: F401
    except ImportError:
        return Found("markx.api_during_run", "mark x", what, -1, 0, note="not measured: this version has no decision job")
    out_of_api = importlib.util.find_spec("insight_core.markx.jobs") is not None

    def work(api: _Api) -> Dict[str, Any]:
        note: Dict[str, Any] = {"where": "insight-ingestion (a process of its own)" if out_of_api else "inside the API"}
        if out_of_api:   # as insight-ingestion runs it: the candidate flush then the decision run, in a process
            job = subprocess.run([sys.executable, "-c", "import sys; from insight_core.markx.jobs import Jobs; "
                                  "out = Jobs(sys.argv[1]).decide(); print(out and {k: out.get(k) for k in ('run', 'skipped')})",
                                  db_url], env=api.env, capture_output=True, text=True, timeout=1800)
            note["job"] = (job.stdout.strip() or job.stderr.strip()[-300:])
            api.get("/api/markx/decide", 10)   # the route only asks now; it is measured with the rest
        else:            # the start's run (flush + decisions) is running in the API; then the page's button
            req = urllib.request.Request(api.base + "/api/markx/decide", method="POST")
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    note["job"] = json.loads(r.read() or b"{}").get("run") or "skipped"
            except Exception as exc:  # noqa: BLE001
                note["job"] = f"POST /api/markx/decide failed: {exc}"
            # and the start's run, with the candidate flush first, to its end (its scheduler logs one line)
            end = time.monotonic() + 1200
            while time.monotonic() < end:
                api.log.flush()
                with open(api.log_name, encoding="utf-8", errors="replace") as fh:
                    if "Mark X decisions:" in fh.read():
                        break
                time.sleep(1)
            else:
                note["start_run"] = "not seen in 1200 s"
        return note
    return _measured(db_url, "markx.api_during_run", what, "api_during_run.log", work)


REBUILD_LIMIT_S = 1200   # the first start's rebuild is measured to its end, or this long (then stopped: the copy is scratch)
FORCED_RULES = "rules of another version (the real-data check's first start)"


def api_during_rebuild(db_url: str, now: datetime) -> Found:
    """0121 Decided 8: the reader's API answers during a deploy's first start after a rule change (the v10.0.1 review
    saw 2.0-5.8 s stalls of the whole API then). The copy's stories are marked as of other rules, as a deploy of new
    rules finds them; then the version's start work runs as its container runs it (the supervisor's child process:
    the search refill and the start's story job, a rule change's rebuild, then Mark X's first run is asked for), while
    the probes run as for markx.api_during_run, and with the same baseline (added_by_run). The rebuild is measured to
    its end, or REBUILD_LIMIT_S, then stopped (the last check: the copy is scratch)."""
    import importlib.util
    import signal
    import subprocess
    what = ("API requests (/api/version, /api/feed) slower than 1 s or failing during a deploy's first start after a "
            "rule change (the rebuild), over the rate before and after it")
    supervised = importlib.util.find_spec("insight_core.scripts.api_supervisor") is not None
    if not supervised:
        return Found("markx.api_during_rebuild", "mark x", what, -1, 0,
                     note="not measured: this version runs its start work inside the API (no supervisor)")
    from insight_core.services.stories_service import SETTINGS_KEY
    with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE system_settings SET value = jsonb_set(value - 'rebuild', '{rules}', to_jsonb(%s::text)) "
                    "WHERE key = %s", (FORCED_RULES, SETTINGS_KEY))

    def progress() -> Dict[str, Any]:
        with open_copy(db_url, writable=True) as conn, conn.cursor() as cur:   # never read_only(): it is process-wide
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
            row = cur.fetchone()
        value = (row[0] if row else None) or {}
        return {"rebuild": value.get("rebuild"), "rules_changed": value.get("rules") != FORCED_RULES}

    def work(api: _Api) -> Dict[str, Any]:
        log = open("api_during_rebuild.start.log", "w", encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-c", "from insight_core.scripts.api_supervisor import start_work; "
                                  "start_work()"], env=api.env, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        try:
            child.wait(REBUILD_LIMIT_S)
            ended = "finished"
        except subprocess.TimeoutExpired:
            ended = f"stopped after {REBUILD_LIMIT_S} s"
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
        finally:
            log.close()
        return {"where": "the supervisor's start work (a process of its own)", "start_work": ended,
                "exit": child.returncode, **progress()}
    return _measured(db_url, "markx.api_during_rebuild", what, "api_during_rebuild.log", work)


def check(db_url: str, now: datetime, identity: str = IDENTITY) -> List[Found]:
    scratch_only(db_url)
    found = rebuild_twice(db_url, now)
    found += markx_unchanged(db_url, now)
    found.append(incremental_identity(db_url, now, identity))   # it holds posts back and brings them in again
    found.append(api_during_run(db_url, now))                  # then: the API's own start may run the story job
    found.append(api_during_rebuild(db_url, now))              # last: it leaves the copy rebuilt by its start (0121 D8)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--now")
    ap.add_argument("--identity", default=IDENTITY, help="module:function of the incremental job's identity check")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    scratch_only(args.db)
    with open_copy(args.db, writable=True) as conn, conn.cursor() as cur:
        now = copy_now(cur, args.now)
    found = check(args.db, now, args.identity)
    for f in found:
        count = "n/a" if f.count < 0 else f"{f.count:>6}"
        print(f"{f.name:<34} {count} of {f.of:<7} {f.seconds:>5}s  {f.what}{'  (' + f.note + ')' if f.note else ''}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"now": now.isoformat(), "found": [asdict(f) for f in found]}, fh, ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
