"""The stamp of a prepared copy (scripts/prepared-db.sh), one JSON line, from the P_* environment the script sets."""
import datetime
import json
import os

e = os.environ
prev = json.loads(e.get("P_PREV") or "{}")
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
after = [v for v in e.get("P_AFTER", "").split(",") if v]
applied = [v for v in e.get("P_APPLIED", "").split(",") if v]
try:
    backfills = json.loads(e.get("P_BF") or "{}")
except ValueError:
    backfills = {"unreadable": e.get("P_BF", "")[:300]}
stamp = {
    "set": e["P_SET"],
    "source": prev.get("source") or e["P_SRC"],
    "source_snapshot": (prev.get("source_snapshot") if (prev.get("source_snapshot") or {}).get("posts") or (prev.get("source_snapshot") or {}).get("from")
                        else json.loads(e.get("P_SNAP") or "{}")),
    "ref": e["P_REF"],
    "commit": e["P_COMMIT"],
    "migrations": len(after),
    "last_migration": after[-1] if after else None,
    "applied_now": applied,
    "backfills": backfills,
    "built_at": prev.get("built_at") or now,
    "refreshed_at": now,
    "seconds": json.loads(e.get("P_SEC") or "{}"),
    "history": (prev.get("history") or [])[-19:] + [{"at": now, "commit": e["P_COMMIT"], "applied": len(applied)}],
}
print(json.dumps(stamp, separators=(",", ":"), default=str))
