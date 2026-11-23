"""GET /metrics: INSIGHT's own numbers in Prometheus' text format (`collect`, `render`; no client library).

Per-process memory and CPU (cAdvisor sees only container totals), each job's runs, the worker's queue, the kept
pages, Postgres' statement time and the newest ingestion run. Read from the logs volume's beat files and one
read-only database transaction, never from the ingestion processes; a failing part is left out and counted in
insight_metrics_part_errors. Labels stay few; a job's label is `insight_job`, never `job` (Prometheus sets `job`
itself and would rename ours). /metrics is outside /api, so nginx never proxies it: only the compose network and the
host reach it.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.utils.env import env_float

logger = get_component_logger("metrics")

MB = 2**20
TOP_STATEMENTS = 5
API_FRESH = 120.0     # an API process's beat older than this is a process that ended: not shown
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
ALERT_RSS_MB = 3072.0  # a process's resident memory past this alerts (INSIGHT_ALERT_RSS_MB)


@dataclass
class Family:
    """One metric: its name, type ("gauge" | "counter"), help, and samples [(labels, value)]."""
    name: str
    type: str
    help: str
    samples: List[Tuple[Dict[str, str], float]] = field(default_factory=list)

    def add(self, value: Any, **labels: Any) -> None:
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        self.samples.append(({k: str(v) for k, v in labels.items()}, number))


# Every family on the page: its type and help (one place, so a part never names a family another describes).
FAMILIES: Dict[str, Tuple[str, str]] = {
    "insight_process_resident_bytes": ("gauge", "A process's resident memory now (VmRSS)."),
    "insight_process_peak_resident_bytes": ("gauge", "A process's high-water resident memory since its start (VmHWM)."),
    "insight_process_cpu_seconds_total": ("counter", "A process's own CPU seconds, user and system."),
    "insight_heartbeat_age_seconds": ("gauge", "Seconds since a loop's last heartbeat."),
    "insight_job_running": ("gauge", "1 while a job's run is in progress."),
    "insight_job_running_seconds": ("gauge", "Seconds the running run has been going."),
    "insight_job_stage_seconds": ("gauge", "Seconds the running run has been in its current stage."),
    "insight_job_wanted_seconds": ("gauge", "Seconds work has waited for a job (0: none waits)."),
    "insight_job_last_duration_seconds": ("gauge", "The last run's duration."),
    "insight_job_last_peak_resident_bytes": ("gauge", "The last run's own peak resident memory."),
    "insight_job_last_cpu_seconds": ("gauge", "The last run's own CPU seconds."),
    "insight_job_last_ok": ("gauge", "1 when the last run ended well, 0 when it failed."),
    "insight_job_runs_total": ("counter", "Runs ended, by result (since migration 0151)."),
    "insight_job_failures_in_a_row": ("gauge", "Failed runs in a row (3 or more: failing)."),
    "insight_job_since_success_seconds": ("gauge", "Seconds since the job's last run that ended well."),
    "insight_decision_last_stage_seconds": ("gauge", "The last decision run's seconds in each stage."),
    "insight_job_current_stage": ("gauge", "1 for the stage a running job is in."),
    "insight_decision_held": ("gauge", "1 while Mark IX's story job holds the decision run."),
    "insight_decision_failing_after": ("gauge", "Failed runs in a row from which a job shows as failing."),
    "insight_rebuild_in_progress": ("gauge", "1 while Mark IX's rule-change rebuild is in progress, 0.5 while one is due, 0 otherwise."),
    "insight_rebuild_done_posts": ("gauge", "Posts the rebuild has regrouped."),
    "insight_rebuild_total_posts": ("gauge", "Posts the rebuild regroups."),
    "insight_rebuild_running_seconds": ("gauge", "Seconds since the rebuild began."),
    "insight_worker_tasks": ("gauge", "Mark X tasks waiting (open) and leased, by kind."),
    "insight_worker_calls_total": ("counter", "Mark X model calls recorded (answers)."),
    "insight_worker_cost_usd_total": ("counter", "Mark X model calls' recorded cost."),
    "insight_worker_answers_last_hour": ("gauge", "Mark X answers recorded in the last hour, by validity."),
    "insight_held_tasks": ("gauge", "Tasks held by the re-ask guard, by kind, status and hold state."),
    "insight_kept_page_age_seconds": ("gauge", "Seconds since a kept page's newest build."),
    "insight_kept_page_rows": ("gauge", "A kept page's rows."),
    "insight_kept_page_bytes": ("gauge", "A kept page's bytes."),
    "insight_db_statements_enabled": ("gauge", "1 when pg_stat_statements is loaded and its view created."),
    "insight_db_statement_seconds_total": ("counter", "Postgres' execution time over every statement of this database since the counts were reset."),
    "insight_db_statement_calls_total": ("counter", "Statements executed since the counts were reset."),
    "insight_db_top_statement_seconds_total": ("counter", "Execution time of the top statements by total time (id: pg_stat_statements' queryid; its text in /api/operations/db-statements)."),
    "insight_db_top_statement_calls_total": ("counter", "Calls of the top statements by total time."),
    "insight_ingestion_last_run_seconds": ("gauge", "The newest ingestion run's duration."),
    "insight_ingestion_last_posts_fetched": ("gauge", "Posts the newest ingestion run fetched."),
    "insight_ingestion_last_posts_inserted": ("gauge", "New posts the newest ingestion run saved."),
    "insight_ingestion_last_run_ok": ("gauge", "1 when the newest ingestion run succeeded (partial: 0.5)."),
    "insight_ingestion_last_run_age_seconds": ("gauge", "Seconds since the newest ingestion run ended."),
    "insight_ingestion_since_success_seconds": ("gauge", "Seconds since the newest successful ingestion run ended."),
    "insight_metrics_part_errors": ("gauge", "1 for a part of this page that could not be read."),
    "insight_build_info": ("gauge", "The running build (always 1)."),
    "insight_alert_process_resident_bytes": ("gauge", "The resident memory above which a process alerts "
                                             "(INSIGHT_ALERT_RSS_MB; deploy/prometheus/insight-alerts.yml)."),
    "insight_metrics_seconds": ("gauge", "Seconds this page took to read."),
}


class Page:
    """The families of one scrape (FAMILIES'), in the order first asked for."""

    def __init__(self) -> None:
        self.families: Dict[str, Family] = {}

    def __call__(self, name: str) -> Family:
        fam = self.families.get(name)
        if fam is None:
            type_, help_ = FAMILIES[name]
            fam = self.families[name] = Family(name, type_, help_)
        return fam


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def render(page: Page) -> str:
    """The text exposition format (version 0.0.4): # HELP and # TYPE once a family, a line a sample."""
    lines: List[str] = []
    for fam in page.families.values():
        if not fam.samples:
            continue
        lines.append(f"# HELP {fam.name} {fam.help.replace(chr(92), chr(92) * 2).replace(chr(10), ' ')}")
        lines.append(f"# TYPE {fam.name} {fam.type}")
        for labels, value in fam.samples:
            label = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels.items())
            lines.append(f"{fam.name}{{{label}}} {_number(value)}" if label else f"{fam.name} {_number(value)}")
    return "\n".join(lines) + "\n"


# ---- the parts --------------------------------------------------------------------------------------------------

def processes(page: Page, procs: Dict[str, Dict[str, Any]], own: Optional[Tuple[int, Dict[str, Any]]] = None) -> None:
    """Each process's own memory and CPU, from its beat (utils/heartbeat.processes); `own`: this API process's
    (pid, numbers) read now, over its beat."""
    rss = page("insight_process_resident_bytes")
    hwm = page("insight_process_peak_resident_bytes")
    cpu = page("insight_process_cpu_seconds_total")
    age = page("insight_heartbeat_age_seconds")
    shown: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for name, p in procs.items():
        if name.startswith("api-"):
            if p.get("age", 0) > API_FRESH:
                continue
            shown[("api", name[4:])] = p
        else:
            age.add(p.get("age"), loop=name)
            if "rss_mb" in p:
                shown[(name, "")] = p
    if own is not None:
        shown[("api", str(own[0]))] = own[1]
    for (process, pid), p in sorted(shown.items()):
        labels = {"process": process, **({"pid": pid} if pid else {})}
        rss.add(_bytes(p.get("rss_mb")), **labels)
        hwm.add(_bytes(p.get("hwm_mb")), **labels)
        cpu.add(p.get("cpu_s"), **labels)


def _bytes(mb: Any) -> Optional[float]:
    try:
        return None if mb is None else float(mb) * MB
    except (TypeError, ValueError):
        return None


def _age(now: datetime, at: Any) -> Optional[float]:
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return None
    if not isinstance(at, datetime):
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0.0, (now - at).total_seconds())


def jobs(page: Page, cur: Any, now: datetime) -> None:
    """Each Mark X / kept-view / rebuild job's runs (mx_jobs), the decision run's stages and holds, Mark IX's rebuild."""
    from insight_core.markx import jobs as mx_jobs
    cur.execute("""SELECT job, stage, stage_at, started_at, wanted_at, failures, runs_ok, runs_failed, ok_at,
                          (last ->> 'ok')::boolean, last -> 'seconds', last -> 'peak_mb', last -> 'cpu_s',
                          CASE WHEN job = 'decide' THEN last -> 'stages' END
                     FROM mx_jobs ORDER BY job""")
    rows = cur.fetchall()
    running = page("insight_job_running")
    running_s = page("insight_job_running_seconds")
    stage_s = page("insight_job_stage_seconds")
    wanted = page("insight_job_wanted_seconds")
    seconds = page("insight_job_last_duration_seconds")
    peak_ = page("insight_job_last_peak_resident_bytes")
    cpu = page("insight_job_last_cpu_seconds")
    ok = page("insight_job_last_ok")
    runs = page("insight_job_runs_total")
    in_a_row = page("insight_job_failures_in_a_row")
    since_ok = page("insight_job_since_success_seconds")
    stages = page("insight_decision_last_stage_seconds")
    current = page("insight_job_current_stage")
    for (job, stage, stage_at, started, wanted_at, failures, n_ok, n_failed, ok_at, last_ok, last_s, last_peak,
         last_cpu, last_stages) in rows:
        running.add(1 if stage is not None else 0, insight_job=job)
        if stage is not None:
            running_s.add(_age(now, started), insight_job=job)
            stage_s.add(_age(now, stage_at), insight_job=job)
            current.add(1, insight_job=job, stage=stage)
        wanted.add(_age(now, wanted_at) if wanted_at is not None else 0, insight_job=job)
        seconds.add(last_s, insight_job=job)
        peak_.add(_bytes(last_peak), insight_job=job)
        cpu.add(last_cpu, insight_job=job)
        if last_ok is not None:
            ok.add(1 if last_ok else 0, insight_job=job)
        runs.add(n_ok, insight_job=job, result="ok")
        runs.add(n_failed, insight_job=job, result="failed")
        in_a_row.add(failures, insight_job=job)
        since_ok.add(_age(now, ok_at), insight_job=job)
        if isinstance(last_stages, list):
            for item in last_stages:
                if isinstance(item, list) and len(item) == 2:
                    stages.add(item[1], stage=item[0])
    ix = mx_jobs.mark_ix(cur)
    held, _ahead = mx_jobs.decision_hold(ix)
    page("insight_decision_held").add(1 if held else 0)
    page("insight_decision_failing_after").add(mx_jobs.FAILING_AFTER)
    rebuild = page("insight_rebuild_in_progress")
    rebuild.add({"in progress": 1, "due": 0.5}.get(ix.get("rebuild") or "", 0))
    if ix.get("rebuild") == "in progress":
        page("insight_rebuild_done_posts").add(ix.get("done") or 0)
        page("insight_rebuild_total_posts").add(ix.get("total"))
        page("insight_rebuild_running_seconds").add(
            _age(now, ix.get("started_at")))


def source_stats(page: Page, cur: Any, now: datetime) -> None:
    """The source stats job (markx/source_stats.py: its state in mx_settings, not mx_jobs)."""
    from insight_core.markx import source_stats as stats
    state = stats.job_state(cur)
    last = state.get("last") or {}
    if not last:
        return
    page("insight_job_last_duration_seconds").add(last.get("seconds"), insight_job="source_stats")
    page("insight_job_last_peak_resident_bytes").add(_bytes(last.get("peak_mb")), insight_job="source_stats")
    page("insight_job_last_cpu_seconds").add(last.get("cpu_s"), insight_job="source_stats")
    page("insight_job_last_ok").add(1 if last.get("ok") else 0, insight_job="source_stats")
    page("insight_job_since_success_seconds").add(_age(now, state.get("last_at")), insight_job="source_stats")


def worker(page: Page, cur: Any, now: datetime) -> None:
    """The worker's queue (kept counts), its calls (a counter) and the last hour's answers; the held tasks."""
    from insight_core.markx import holds, kept_counts
    tasks = page("insight_worker_tasks")
    for kind, by_status in kept_counts.queue_counts(cur).items():
        for status in ("open", "leased"):
            tasks.add(by_status.get(status, 0), kind=kind, status=status)
    calls = kept_counts.call_totals(cur)
    page("insight_worker_calls_total").add(calls[0])
    page("insight_worker_cost_usd_total").add(float(calls[3]))
    cur.execute("""SELECT count(*) FILTER (WHERE valid), count(*) FILTER (WHERE NOT valid)
                     FROM mx_calls WHERE created_at > now() - interval '1 hour'""")
    valid, invalid = cur.fetchone()
    hour = page("insight_worker_answers_last_hour")
    hour.add(valid, valid="true")
    hour.add(invalid, valid="false")
    held = page("insight_held_tasks")
    sums: Dict[Tuple[str, str, str], int] = {}
    for h in holds.held(cur):
        for status in ("open", "leased"):
            key = (h["kind"], status, h["state"])
            sums[key] = sums.get(key, 0) + h[status]
    for (kind, status, state), n in sorted(sums.items()):
        held.add(n, kind=kind, status=status, state=state)


def kept_pages(page: Page, cur: Any, now: datetime) -> None:
    """The kept pages (mx_kept_pages): each page's newest build's age, its rows and bytes."""
    cur.execute("""SELECT page, extract(epoch FROM now() - max(built_at)), count(*), sum(bytes)
                     FROM mx_kept_pages GROUP BY page ORDER BY page""")
    age = page("insight_kept_page_age_seconds")
    rows = page("insight_kept_page_rows")
    size = page("insight_kept_page_bytes")
    for name, seconds, n, total in cur.fetchall():
        age.add(seconds, page=name)
        rows.add(n, page=name)
        size.add(total, page=name)


def statements(page: Page, cur: Any, now: datetime) -> None:
    """Postgres' statement time (pg_stat_statements, operations_service.top_statements: the same reading as
    /api/operations/db-statements, without the text)."""
    from insight_core.services.operations_service import top_statements
    top = top_statements(cur, TOP_STATEMENTS, chars=0)
    page("insight_db_statements_enabled").add(
        1 if top.get("enabled") else 0)
    if not top.get("enabled"):
        return
    page("insight_db_statement_seconds_total").add(top["total_ms"] / 1000.0)
    page("insight_db_statement_calls_total").add(
        top["calls"])
    t = page("insight_db_top_statement_seconds_total")
    c = page("insight_db_top_statement_calls_total")
    for s in top["statements"]:
        t.add(s["total_ms"] / 1000.0, id=s["id"])
        c.add(s["calls"], id=s["id"])


def ingestion(page: Page, cur: Any, now: datetime) -> None:
    """The newest finished ingestion run (job_runs): its seconds, posts fetched and saved, how it ended; and the age of
    the newest successful one."""
    cur.execute("""SELECT status, finished_at, payload -> 'duration_s', payload -> 'posts_fetched',
                          payload -> 'posts_inserted'
                     FROM job_runs WHERE job_type = 'ingestion_run' AND finished_at IS NOT NULL
                    ORDER BY started_at DESC LIMIT 1""")
    row = cur.fetchone()
    if row is not None:
        status, finished, duration, fetched, inserted = row
        page("insight_ingestion_last_run_seconds").add(duration)
        page("insight_ingestion_last_posts_fetched").add(fetched)
        page("insight_ingestion_last_posts_inserted").add(inserted)
        page("insight_ingestion_last_run_ok").add(
            {"success": 1, "partial": 0.5}.get(status, 0))
        page("insight_ingestion_last_run_age_seconds").add(
            _age(now, finished))
    cur.execute("""SELECT max(finished_at) FROM job_runs
                    WHERE job_type = 'ingestion_run' AND status IN ('success', 'partial')
                      AND started_at > now() - interval '30 days'""")
    page("insight_ingestion_since_success_seconds").add(_age(now, cur.fetchone()[0]))


PARTS: Tuple[Tuple[str, Callable[..., None]], ...] = (
    ("jobs", jobs), ("source_stats", source_stats), ("worker", worker), ("kept_pages", kept_pages),
    ("statements", statements), ("ingestion", ingestion))


def collect(db_url: str, *, now: Optional[datetime] = None, procs: Optional[Dict[str, Dict[str, Any]]] = None,
            own: Optional[Tuple[int, Dict[str, Any]]] = None) -> Page:
    """One scrape's families: the processes' beats, then each part in a savepoint of one read-only transaction (a part
    that fails is logged, left out and counted)."""
    from insight_core.db import database
    from insight_core.utils import heartbeat
    t0 = time.monotonic()
    page = Page()
    now = now or datetime.now(timezone.utc)
    processes(page, heartbeat.processes(now.timestamp()) if procs is None else procs, own)
    errors = page("insight_metrics_part_errors")
    with database.transaction(db_url) as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        for name, part in PARTS:
            try:
                with cur.connection.transaction():
                    part(page, cur, now)
            except Exception:  # noqa: BLE001 - one part never empties the page
                logger.exception("Metrics: the %s part failed", name)
                errors.add(1, part=name)
    version = os.getenv("INSIGHT_VERSION") or "dev"
    page("insight_build_info").add(
        1, version=version, commit=(os.getenv("INSIGHT_COMMIT") or "")[:12])
    page("insight_alert_process_resident_bytes").add(_bytes(env_float("INSIGHT_ALERT_RSS_MB", ALERT_RSS_MB)))
    page("insight_metrics_seconds").add(round(time.monotonic() - t0, 4))
    return page


def exposition(db_url: str, **kwargs: Any) -> str:
    """GET /metrics' body: `collect` rendered (`render`)."""
    return render(collect(db_url, **kwargs))
