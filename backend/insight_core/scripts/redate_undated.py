"""Date again the posts a feed gave no date that were stored as "first seen" (v10.30, once).

    python -m insight_core.scripts.redate_undated [--dry-run] [--source ID]

A feed that dates only its recent items (a blog's archive left undated) gave its old items the time they were first
seen (issue 0137 B9): a 2015 post read on a first fetch was this week's news, in News, tracks and briefs. New reads
are bounded by parsing._bound_undated; this repairs the posts stored before it. For each enabled feed source with
posts stored as "seen": its feed is read once (one request a source), parsed as a new read is, and each stored
"seen" post whose item now has a bound older than its stored date takes that bound (published_precision "none": no
date given). Nothing else is written; --dry-run writes nothing and prints what a run would change. JSON summary.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Sequence

import psycopg

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds.parsing import parse_feed_posts
from insight_core.utils.url_normalization import normalize_url


def sources(conn: psycopg.Connection, source_id: Optional[str]) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("""SELECT s.id::text, s.handle_or_url, count(*) FROM sources s JOIN posts p ON p.source_id = s.id
                        WHERE s.enabled AND s.platform = 'rss' AND p.published_precision = 'seen'
                          AND (%s::uuid IS NULL OR s.id = %s::uuid)
                          AND s.handle_or_url ~* '^https?://' AND NOT (s.settings ? 'page_watch')
                        GROUP BY 1, 2 ORDER BY 3 DESC""", (source_id, source_id))
        return [{"id": i, "url": u, "seen": n} for i, u, n in cur.fetchall()]


async def run(db_url: str, *, dry_run: bool, source_id: Optional[str]) -> Dict[str, Any]:
    http = KindHttp()
    out: Dict[str, Any] = {"sources": [], "posts": 0, "dry_run": dry_run}
    with psycopg.connect(db_url) as conn:
        for s in sources(conn, source_id):
            try:
                text, _h = await http.get_text(s["url"])
                drafts = parse_feed_posts(text, s["url"])
            except Exception as e:  # noqa: BLE001 - one source's failure is reported, the rest go on
                out["sources"].append({"source": s["id"], "error": str(e)[:200]})
                continue
            bound = {}
            for d in drafts:
                if d.get("date_precision") == "before" and d.get("url"):
                    for u in {d["url"], normalize_url(d["url"])}:
                        if u:
                            bound[u] = d["date"]
            changed = 0
            with conn.cursor() as cur:
                cur.execute("""SELECT id::text, url, normalized_url, published_at FROM posts
                                WHERE source_id = %s AND published_precision = 'seen'""", (s["id"],))
                for pid, url, nurl, at in cur.fetchall():
                    b = bound.get(url) or bound.get(nurl or "")
                    if b is None or (at is not None and at <= b):
                        continue
                    changed += 1
                    if not dry_run:
                        cur.execute("""UPDATE posts SET published_at = %s, published_precision = 'none'
                                        WHERE id = %s AND published_precision = 'seen'""", (b, pid))
            if not dry_run:
                conn.commit()
            out["sources"].append({"source": s["id"], "url": s["url"], "seen": s["seen"], "redated": changed})
            out["posts"] += changed
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source")
    args = ap.parse_args(argv)
    db_url = os.environ["DATABASE_URL"]
    print(json.dumps(asyncio.run(run(db_url, dry_run=args.dry_run, source_id=args.source)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
