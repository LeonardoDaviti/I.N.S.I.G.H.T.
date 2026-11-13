"""`scripts/prepared-db.sh list`: one line a prepared copy from `name<TAB>size<TAB>stamp json` lines on stdin."""
import json
import sys

for line in sys.stdin:
    name, size, stamp = (line.rstrip("\n").split("\t") + ["", ""])[:3]
    try:
        s = json.loads(stamp)
    except ValueError:
        s = {}
    snap = s.get("source_snapshot") or {}
    if "from" in snap:   # scale: the snapshot prep_mxreal came from
        snap = snap.get("from") or {}
    print(f"{name:<18} {size:>8}  commit {s.get('commit')}  last migration {s.get('last_migration')}  "
          f"source {s.get('source')} ({snap.get('posts', '?')} posts to {str(snap.get('last_fetched', '?'))[:10]})  "
          f"refreshed {s.get('refreshed_at')}")
