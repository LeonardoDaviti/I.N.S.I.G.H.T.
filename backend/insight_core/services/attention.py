"""Needs attention (0280 I): one check over the signals INSIGHT already has, so the reader is told.

    refresh_if_due(db_url)      the jobs process, after an ingestion run (ports.keep_derived): at most every EVERY
    kept(db_url)                GET /api/operations/attention: the kept answer, never computed in a request

`build` is the pure rule over what is read (`read_signals`): the source health rows (services/operations_service
health_row), Mark X's kept queue counts and a day's answers, the database's size and statement totals, and the
previous answer (its `history`: what a week-over-week comparison needs, kept in the same row). Every item is
{key, kind, level, title, detail, since?, source_id?, host?}; `level` "act" is counted in the badge, "watch" and
"info" are listed only. Nothing names a source, a site or a platform: kinds and hosts come from the rows.

Rules (none tuned on one site; each is a signal 0280 G names):
- a source failing (backoff or its last fetch an error, enabled): act, with its error and since its last success;
- a source silent far past its own rhythm (health's `silent`): watch;
- a whole kind of source quiet or failing at once (every source of a kind with PLATFORM_MIN or more failing, or no
  post from any for PLATFORM_QUIET_GAPS of its busiest source's gap, at least a day): act (a bridge is down);
- a page watch whose listing lands at another page (health's `lands_at`): act;
- a host answering "blocked" or "rate limited" (401/403/429/451) to any source within the week: act, per host;
- Mark X: new failed tasks per kind (and its guide) within the week: act; an open queue larger than a day's
  answers: act;
- the database's size and its slowest statements, this week against the week before: info.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from insight_core.utils.addresses import host_of

logger = logging.getLogger("insight.services.attention")

KEY = "attention"                         # system_settings row
EVERY = timedelta(minutes=30)             # not measured: an hourly tick, a check twice as often is enough
WEEK = timedelta(days=7)
KEEP_DAYS = 15                            # daily snapshots kept: this week and the week before
PLATFORM_MIN = 3                          # a kind with fewer sources is no platform (one dead source is a source)
PLATFORM_QUIET_GAPS = 3                   # as health's stalled: 3 of the busiest source's gaps is rarely chance
BLOCKED_STATUSES = (401, 403, 429, 451)
STATEMENTS_KEPT = 200                     # each day's statement snapshot: the costliest so far
STATEMENTS_SHOWN = 5
_STATUS_RE = re.compile(r"\bHTTP (\d{3})\b")
_LIMITED_RE = re.compile(r"rate[- ]limit|too many requests", re.I)


def _at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _span(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 48:
        return f"{max(1, round(hours))} h"
    return f"{round(hours / 24)} days"


def _bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def blocked_status(row: Mapping[str, Any]) -> Optional[int]:
    """The "blocked" or "rate limited" status a source's last failing fetch answered, else None."""
    if row.get("last_outcome") != "error" and row.get("status") != "backoff":
        return None
    server = row.get("server_error") or {}
    status = server.get("status") if isinstance(server, dict) else None
    error = str(row.get("last_error") or "")
    if status is None:
        found = _STATUS_RE.search(error)
        status = int(found.group(1)) if found else None
    if status in BLOCKED_STATUSES:
        return int(status)
    return 429 if _LIMITED_RE.search(error) else None


def _host(row: Mapping[str, Any]) -> str:
    server = row.get("server_error") or {}
    if isinstance(server, dict) and server.get("site"):
        return str(server["site"])
    return host_of(str(row.get("address") or row.get("display_name") or "")) or str(row.get("display_name") or "")


def _source_items(rows: List[Mapping[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        if not row.get("enabled"):
            continue
        name = str(row.get("display_name") or row.get("address") or row.get("source_id"))
        failing = row.get("status") == "backoff" or row.get("last_outcome") == "error"
        stalled = row.get("stalled") or None
        if failing or stalled:
            server = row.get("server_error") or {}
            if isinstance(server, dict) and server.get("status") and server.get("site"):
                detail = f"{server['site']} answers {server['status']}"
            else:
                detail = " ".join(str(row.get("last_error") or (stalled or {}).get("reason")
                                      or "its fetches fail").split())[:200]
            since = _at(row.get("last_success_at"))
            failures = int(row.get("consecutive_failures") or 0)
            extra = [f"{failures} failures in a row"] if failures else []
            if since:
                extra.append(f"last worked {_span(now - since)} ago")
            elif stalled and stalled.get("days"):
                extra.append(f"no post in {stalled['days']} days")
            items.append({"key": f"source:{row.get('source_id')}", "kind": "source", "level": "act", "title": name,
                          "detail": "; ".join([detail, *extra]), "since": _iso(since),
                          "source_id": row.get("source_id")})
        elif row.get("silent"):
            silent = row["silent"]
            gap = silent.get("usual_gap_hours")
            usual = f" (it posts every {_span(timedelta(hours=gap))})" if gap else ""
            items.append({"key": f"silent:{row.get('source_id')}", "kind": "silent", "level": "watch", "title": name,
                          "detail": f"no post in {silent.get('days')} days{usual}",
                          "since": silent.get("last_post_at"), "source_id": row.get("source_id")})
        if row.get("lands_at"):
            items.append({"key": f"lands:{row.get('source_id')}", "kind": "moved", "level": "act", "title": name,
                          "detail": f"{row.get('address')} now lands at {row['lands_at']}",
                          "source_id": row.get("source_id")})
    return items


def _platform_items(rows: List[Mapping[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    by_kind: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("enabled") and row.get("kind"):
            by_kind[str(row["kind"])].append(row)
    items = []
    for kind, members in sorted(by_kind.items()):
        if len(members) < PLATFORM_MIN:
            continue
        tried = [r for r in members if r.get("last_outcome")]
        if tried and all(r.get("last_outcome") == "error" for r in tried) and len(tried) >= PLATFORM_MIN:
            errors = sorted({str(r.get("last_error") or "")[:80] for r in tried})
            items.append({"key": f"platform:{kind}", "kind": "platform", "level": "act",
                          "title": f"Every {kind} source fails",
                          "detail": f"{len(tried)} of {len(members)} failed their last fetch: {'; '.join(errors[:3])}"})
            continue
        newest = max((at for r in members if (at := _at(r.get("last_post_at")))), default=None)
        gaps = [float(r["mean_gap_hours"]) for r in members if r.get("mean_gap_hours")]
        if newest is None or not gaps:
            continue
        quiet = max(timedelta(days=1), PLATFORM_QUIET_GAPS * timedelta(hours=min(gaps)))
        if now - newest > quiet:
            items.append({"key": f"platform:{kind}", "kind": "platform", "level": "act",
                          "title": f"No {kind} source has posted for {_span(now - newest)}",
                          "detail": f"{len(members)} sources; the busiest posts every {_span(timedelta(hours=min(gaps)))}",
                          "since": _iso(newest)})
    return items


def _blocked(rows: List[Mapping[str, Any]], history: Mapping[str, Any], now: datetime
             ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Hosts answering blocked / rate limited now, merged into the week's (history["blocked"]: {host: {first_at,
    last_at, statuses, sources}}): one act item per host seen within the week."""
    seen: Dict[str, Dict[str, Any]] = {h: dict(v) for h, v in (history.get("blocked") or {}).items()
                                       if (_at(v.get("last_at")) or now) > now - WEEK}
    for row in rows:
        status = blocked_status(row) if row.get("enabled") else None
        if status is None:
            continue
        host = _host(row)
        entry = seen.setdefault(host, {"first_at": now.isoformat(), "statuses": [], "sources": []})
        entry["last_at"] = now.isoformat()
        entry["statuses"] = sorted({*entry.get("statuses", []), status})
        entry["sources"] = sorted({*entry.get("sources", []), str(row.get("display_name") or row.get("source_id"))})[:10]
    # a host whose sources fail now is listed by them (act); its week stays listed here (watch)
    failing_now = {_host(r) for r in rows if r.get("enabled") and blocked_status(r) is not None}
    items = [{"key": f"blocked:{host}", "kind": "blocked", "level": "watch" if host in failing_now else "act",
              "host": host,
              "title": f"{host} blocks or limits INSIGHT",
              "detail": (f"answered {', '.join(map(str, v['statuses']))} to {', '.join(v['sources'][:3])}"
                         + (f" and {len(v['sources']) - 3} more" if len(v["sources"]) > 3 else "")
                         + f"; last {_span(now - (_at(v.get('last_at')) or now))} ago"),
              "since": v.get("first_at")} for host, v in sorted(seen.items())]
    return items, seen


def _day_back(snapshots: List[Mapping[str, Any]], now: datetime, back: timedelta) -> Optional[Mapping[str, Any]]:
    """The newest daily snapshot at least `back` old, if any."""
    old = [s for s in snapshots if (_at(s.get("at")) or now) <= now - back]
    return old[-1] if old else None


def _markx_items(markx: Optional[Mapping[str, Any]], snapshots: List[Mapping[str, Any]], now: datetime
                 ) -> List[Dict[str, Any]]:
    if not markx:
        return []
    items = []
    queue: Mapping[str, Mapping[str, int]] = markx.get("queue") or {}
    guides: Mapping[str, str] = markx.get("guides") or {}
    week_ago = _day_back(snapshots, now, WEEK) or (snapshots[0] if snapshots else None)
    before = (week_ago or {}).get("failed") or {}
    for kind, counts in sorted(queue.items()):
        failed = int(counts.get("failed") or 0)
        new = failed - int(before.get(kind, 0)) if week_ago else None
        guide = f" ({guides[kind]})" if guides.get(kind) else ""
        if new is not None and new > 0:
            answered = int(counts.get("answered") or 0)
            share = f"; {failed / (failed + answered):.1%} of its tasks" if failed + answered else ""
            items.append({"key": f"failed:{kind}", "kind": "failed_tasks", "level": "act",
                          "title": f"Mark X {kind}{guide}: {new} new failed tasks",
                          "detail": f"{failed} failed in all{share}; since {week_ago.get('at', '')[:10]}"})
        elif new is None and failed:
            # no snapshot to compare yet: listed, not counted (failed tasks stay failed: only new ones are news)
            answered = int(counts.get("answered") or 0)
            items.append({"key": f"failed:{kind}", "kind": "failed_tasks", "level": "watch",
                          "title": f"Mark X {kind}{guide}: {failed} failed tasks",
                          "detail": f"{failed / (failed + answered):.1%} of its tasks; new ones are counted from tomorrow"})
    open_tasks = sum(int(c.get("open") or 0) + int(c.get("leased") or 0) for c in queue.values())
    day = markx.get("answers_day")
    if day is not None and open_tasks > int(day):
        items.append({"key": "queue", "kind": "queue", "level": "act",
                      "title": f"Mark X's open queue ({open_tasks:,}) is more than a day's answers ({int(day):,})",
                      "detail": "the worker falls behind: at this rate the queue takes "
                                + (f"{open_tasks / day:.1f} days" if day else "forever")})
    return items


def _db_items(database: Optional[Mapping[str, Any]], snapshots: List[Mapping[str, Any]], now: datetime
              ) -> List[Dict[str, Any]]:
    if not database:
        return []
    items = []
    size = database.get("bytes")
    week_ago = _day_back(snapshots, now, WEEK)
    if size is not None:
        grew = ""
        if week_ago and week_ago.get("db_bytes"):
            delta = size - week_ago["db_bytes"]
            grew = f"; {'+' if delta >= 0 else '-'}{_bytes(abs(delta))} ({delta / week_ago['db_bytes']:+.1%}) since {week_ago['at'][:10]}"
        items.append({"key": "db_size", "kind": "db_size", "level": "info", "title": f"Database {_bytes(size)}",
                      "detail": f"kept everything{grew}"})
    now_counts: Mapping[str, List[float]] = database.get("statements") or {}
    texts: Mapping[str, str] = database.get("texts") or {}
    if week_ago and week_ago.get("statements"):
        then = week_ago["statements"]
        two_weeks = _day_back(snapshots, now, 2 * WEEK)
        earlier = (two_weeks or {}).get("statements") or {}
        week = []
        for qid, (calls, ms) in now_counts.items():
            if qid in then and ms >= then[qid][1]:
                d_calls, d_ms = calls - then[qid][0], ms - then[qid][1]
                prior = (then[qid][1] - earlier[qid][1]) if qid in earlier and then[qid][1] >= earlier[qid][1] else None
                week.append((d_ms, d_calls, prior, qid))
        week.sort(reverse=True)
        for d_ms, d_calls, prior, qid in week[:STATEMENTS_SHOWN]:
            was = f" (the week before {prior / 1000:,.0f} s)" if prior is not None else ""
            items.append({"key": f"statement:{qid}", "kind": "statement", "level": "info",
                          "title": f"{d_ms / 1000:,.0f} s in {int(d_calls):,} calls this week{was}",
                          "detail": " ".join(str(texts.get(qid) or qid).split())[:240]})
    return items


def snapshot(previous: List[Mapping[str, Any]], now: datetime, *, markx: Optional[Mapping[str, Any]],
             database: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The daily snapshots with today's (one a day, the first of the day kept), KEEP_DAYS of them."""
    out = [dict(s) for s in previous if (_at(s.get("at")) or now) > now - timedelta(days=KEEP_DAYS)]
    if out and str(out[-1].get("at", ""))[:10] == now.date().isoformat():
        return out
    today: Dict[str, Any] = {"at": now.isoformat()}
    if markx:
        today["failed"] = {k: int(c.get("failed") or 0) for k, c in (markx.get("queue") or {}).items()}
    if database:
        today["db_bytes"] = database.get("bytes")
        top = sorted((database.get("statements") or {}).items(), key=lambda kv: -kv[1][1])[:STATEMENTS_KEPT]
        today["statements"] = {q: list(v) for q, v in top}
    return [*out, today]


ORDER = {"act": 0, "watch": 1, "info": 2}


def build(rows: List[Mapping[str, Any]], *, now: datetime, previous: Optional[Mapping[str, Any]] = None,
          markx: Optional[Mapping[str, Any]] = None, database: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The answer: {computed_at, count (act items), items (act, watch, info), line (the briefing's), history}."""
    history = dict((previous or {}).get("history") or {})
    snapshots = list(history.get("days") or [])
    blocked_items, blocked = _blocked(rows, history, now)
    items = [*_platform_items(rows, now), *_source_items(rows, now), *blocked_items,
             *_markx_items(markx, snapshots, now), *_db_items(database, snapshots, now)]
    items.sort(key=lambda i: (ORDER[i["level"]], i["kind"] != "platform", i["kind"], str(i["title"]).lower()))
    act = [i for i in items if i["level"] == "act"]
    return {"computed_at": now.isoformat(), "count": len(act), "items": items, "line": briefing_line(act),
            "history": {"blocked": blocked, "days": snapshot(snapshots, now, markx=markx, database=database)}}


def briefing_line(act: List[Mapping[str, Any]], shown: int = 3) -> Optional[str]:
    """"Needs attention (5): Hacker News: hnrss.org answers 502; ..." or None when nothing does."""
    if not act:
        return None
    named = [f"{i['title']}: {str(i['detail']).split(';')[0]}" if i["kind"] == "source" else str(i["title"])
             for i in act[:shown]]
    more = f"; and {len(act) - shown} more" if len(act) > shown else ""
    return f"Needs attention ({len(act)}): " + "; ".join(named) + more


# --------------------------------------------------------------------------- reads and the kept row


def read_signals(db_url: str, ops: Any) -> Dict[str, Any]:
    """What `build` reads: the health rows, Mark X's (when on), the database's. Each part that can't be read is None
    (and logged): the check says what it could."""
    from insight_core.db import database as db
    from insight_core.services.operations_service import statement_counts

    rows = ops.get_source_health()["rows"]
    markx = database = None
    try:
        from insight_core.markx import api as markx_api, kept_counts, repo as mx_repo
        if markx_api.enabled():
            with db.connection(db_url) as conn, conn.cursor() as cur:
                queue = kept_counts.queue_counts(cur)
                run = mx_repo.last_run(cur) or {}
                cur.execute("SELECT count(*) FROM mx_calls WHERE created_at >= now() - interval '1 day'")
                day = int(cur.fetchone()[0])
            guides = ((run.get("config") or {}).get("guides") or {}) if isinstance(run, dict) else {}
            markx = {"queue": queue, "guides": guides, "answers_day": day}
    except Exception:  # noqa: BLE001
        logger.exception("Attention: could not read Mark X's queue")
    try:
        with db.connection(db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            size = int(cur.fetchone()[0])
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')")
            counts, texts = {}, {}
            if cur.fetchone()[0]:
                top = sorted(statement_counts(cur).items(), key=lambda kv: -kv[1][1])[:STATEMENTS_KEPT]
                counts = {q: [v[0], v[1]] for q, v in top}
                cur.execute("""SELECT DISTINCT ON (queryid) queryid::text, left(query, 240) FROM pg_stat_statements
                                WHERE queryid = ANY(%s::bigint[])""", ([int(q) for q in counts][:STATEMENTS_KEPT],))
                texts = dict(cur.fetchall())
        database = {"bytes": size, "statements": counts, "texts": texts}
    except Exception:  # noqa: BLE001
        logger.exception("Attention: could not read the database's size and statements")
    return {"rows": rows, "markx": markx, "database": database}


def kept(db_url: str) -> Optional[Dict[str, Any]]:
    """The kept answer (without its history), or None before the first check."""
    from insight_core.db import database as db
    from insight_core.db.repo_operations import SystemSettingsRepository

    with db.connection(db_url) as conn, conn.cursor() as cur:
        got = SystemSettingsRepository.get(cur, KEY)
    if not got or not isinstance(got[0], dict):
        return None
    return {k: v for k, v in got[0].items() if k != "history"}


def refresh_if_due(db_url: str, *, now: Optional[datetime] = None, ops: Any = None, force: bool = False
                   ) -> Optional[int]:
    """Check again when the kept answer is EVERY old (or `force`): its count, or None when not due."""
    from insight_core.db import database as db
    from insight_core.db.repo_operations import SystemSettingsRepository

    now = now or datetime.now(timezone.utc)
    with db.connection(db_url) as conn, conn.cursor() as cur:
        got = SystemSettingsRepository.get(cur, KEY)
    previous = got[0] if got and isinstance(got[0], dict) else None
    at = _at((previous or {}).get("computed_at"))
    if not force and at is not None and now - at < EVERY:
        return None
    if ops is None:
        from insight_core.services.operations_service import OperationsService
        ops = OperationsService(db_url)
    signals = read_signals(db_url, ops)
    answer = build(signals["rows"], now=now, previous=previous, markx=signals["markx"], database=signals["database"])
    with db.connection(db_url) as conn, conn.cursor() as cur:
        SystemSettingsRepository.upsert(cur, KEY, answer)
        conn.commit()
    logger.info("Attention: %s items need attention (%s listed)", answer["count"], len(answer["items"]))
    return answer["count"]

