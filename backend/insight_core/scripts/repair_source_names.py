"""Name the sources that have no name (issue 0178), once: each by what its feed or page calls itself.

    python -m insight_core.scripts.repair_source_names                # dry run: reports, changes nothing
    python -m insight_core.scripts.repair_source_names --apply        # names what the report lists
    python -m insight_core.scripts.repair_source_names --no-fetch     # no request: the stored evidence only
    python -m insight_core.scripts.repair_source_names --source <id>  # one source

For each source with no display_name (saved pages aside) the name is, first found: what its address says
(source_names.address_name); the name another source of the same platform account has (never a website's
section); unless --no-fetch, what its feed or page calls itself (source_names.own_name), PAGE_GAP_S apart.
A name the owner set is never written over (SourcesRepository.name_if_unnamed checks it again). Nothing is
deleted. Prints the report as JSON: `would_name`, `named`, and the ones left unnamed with why.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db import database as db  # noqa: E402
from insight_core.db.repo_sources import SourcesRepository  # noqa: E402
from insight_core.ingestion import source_names  # noqa: E402

logger = logging.getLogger("insight.repair_source_names")

PAGE_GAP_S = 1.0     # between two sources' requests (one source at a time)
# the accounts a name is shared across (a channel and a bridge's feed of it); a website's sections are not one
PLATFORM_ACCOUNTS = ("t.me/", "x.com/", "reddit.com/r/", "youtube.com/")


def unnamed_sources(cur: Any, source_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The sources with no name (empty or spaces), the owner's saved pages aside, every one or one."""
    cur.execute("""SELECT id::text, platform, handle_or_url, COALESCE(settings, '{}'::jsonb) FROM sources
                    WHERE COALESCE(btrim(settings->>'display_name'), '') = '' AND platform <> 'saved'
                      AND (%s::uuid IS NULL OR id = %s::uuid)
                    ORDER BY platform, handle_or_url""", (source_id, source_id))
    return [{"id": i, "platform": p, "handle_or_url": h, "settings": s or {}} for i, p, h, s in cur.fetchall()]


def account_names(cur: Any) -> Dict[str, str]:
    """{account: the name a named source of it has} (repo_stories.source_account's form), the first by id."""
    from insight_core.db.repo_stories import source_account

    cur.execute("""SELECT platform, handle_or_url, btrim(settings->>'display_name') FROM sources
                    WHERE COALESCE(btrim(settings->>'display_name'), '') <> '' ORDER BY id""")
    out: Dict[str, str] = {}
    for platform, handle, name in cur.fetchall():
        account = source_account(platform, handle)
        if account and account.startswith(PLATFORM_ACCOUNTS) and account not in out:
            out[account] = name
    return out


async def run(db_url: str, *, apply: bool = False, fetch: bool = True, source_id: Optional[str] = None,
              http: Any = None, gap_s: float = PAGE_GAP_S) -> Dict[str, Any]:
    from insight_core.db.repo_stories import source_account

    with db.connection(db_url) as conn, conn.cursor() as cur:
        sources = unnamed_sources(cur, source_id)
        siblings = account_names(cur)
    if fetch and http is None:
        from insight_core.ingestion.http import KindHttp
        http = KindHttp(timeout=10)
    report: Dict[str, Any] = {"unnamed": len(sources), "would_name": 0, "named": 0, "sources": [], "left": []}
    repo = SourcesRepository(db_url)
    asked = False
    for source in sources:
        name, came_from = source_names.address_name(source["platform"], source["handle_or_url"]), "address"
        if not name:
            account = source_account(source["platform"], source["handle_or_url"])
            name, came_from = (siblings.get(account) if account else None), "same account"
        if not name and fetch:
            if asked and gap_s:
                await asyncio.sleep(gap_s)
            asked = True
            name, came_from = await source_names.own_name(http, source), "its feed or page"
        row = {"source_id": source["id"], "platform": source["platform"], "address": source["handle_or_url"]}
        if not name:
            report["left"].append({**row, "why": "no name found" if fetch or source["platform"] != "rss"
                                   else "not asked (--no-fetch)"})
            continue
        report["would_name"] += 1
        row.update(name=name, came_from=came_from)
        if apply:
            with db.transaction(db_url) as cur:
                row["written"] = repo.name_if_unnamed(cur, source["id"], name)
            report["named"] += int(row["written"])
        report["sources"].append(row)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--apply", action="store_true", help="write the names (default: a dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="no request: the address and same-account names only")
    ap.add_argument("--source", help="one source id")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    db_url = args.db
    if not db_url:
        from insight_core.db.ensure_db import ensure_database
        db_url = ensure_database()
    out = asyncio.run(run(db_url, apply=args.apply, fetch=not args.no_fetch, source_id=args.source))
    print(json.dumps({"dry_run": not args.apply, **out}, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
