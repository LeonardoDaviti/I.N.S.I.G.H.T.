"""v10.44: a track's things at production size (~4k rows, ~6k reports, chains of merged rows): one things answer reads
the track's roots once and its kind's reports once, and the repair reads each kind's reports once, not once a split-off
row. Synthetic data only; DB tests on _test only. Prints the timings (the before/after of v10.44's report)."""
from __future__ import annotations

import json
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from insight_core.markx import track_things as TT
from insight_core.tests.test_track_briefer_0245 import _Briefer, v

SCHEMA = TT.with_practice({"kinds": [{"kind": "setup", "about": "one model run on one machine", "fields": [
    {"name": "setup_name", "type": "text", "key": True, "about": "the model"},
    {"name": "hardware", "type": "text", "key": True, "about": "the machine"},
    {"name": "speed", "type": "number", "unit": "tok/s", "about": "tokens a second"},
    {"name": "link", "type": "link", "about": "a page"}]}]})

MODELS = [f"Zqm{n} {s}B" for n in range(150) for s in (4, 27)]            # 300 model names
MACHINES = [f"Zqcard {n} {g}GB" for n in range(120) for g in (12, 24)]    # 240 machines


class Scale(_Briefer):
    ROWS, REPORTS, POSTS = 2600, 6000, 3000

    def build(self):
        """A track like Local Setups at its size: rows of one model name on many machines (the v10.41 joins), a third
        of the rows merged into another (chains), practices one a post."""
        rnd = random.Random(1044)
        f = self.track("setups")
        with self.conn.transaction():
            version = TT._put_schema(self.cur, f, SCHEMA, by="haiku", track_version=1)
        src = self.sources[f]
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.cur.execute("""INSERT INTO posts (source_id, url, normalized_url, title, content, published_at)
                            SELECT %s, u, u, 'Post ' || n, 'text ' || n, %s + n * interval '1 hour'
                              FROM (SELECT n, 'https://test.invalid/scale/' || n || '/' || md5(random()::text) AS u
                                      FROM generate_series(1, %s) n) x RETURNING id::text""", (src, t0, self.POSTS))
        posts = [r[0] for r in self.cur.fetchall()]
        ids = [str(uuid.uuid4()) for _ in range(self.ROWS)]
        kinds = ["setup" if i < self.ROWS * 0.6 else TT.PRACTICE_KIND for i in range(self.ROWS)]
        into = [None] * self.ROWS
        for i in range(self.ROWS):   # a third merged, into an earlier row of its kind (chains of 2-3)
            if i > 10 and rnd.random() < 0.33:
                j = rnd.randrange(i)
                if kinds[j] == kinds[i]:
                    into[i] = ids[j]
        self.cur.execute("""INSERT INTO mx_track_things (id, track_id, kind, key, schema_version, status, merged_into,
                                                         merged_by)
                            SELECT i, %s, k, 'k', %s, CASE WHEN m IS NULL THEN 'current' ELSE 'merged' END, m,
                                   CASE WHEN m IS NULL THEN NULL ELSE 'key' END
                              FROM unnest(%s::uuid[], %s::text[], %s::uuid[]) AS x(i, k, m)""",
                         (f, version, ids, kinds, into))
        rows = []
        for n in range(self.REPORTS):
            i = rnd.randrange(self.ROWS)
            p = posts[rnd.randrange(self.POSTS)]
            if kinds[i] == "setup":
                vals = {"setup_name": v(rnd.choice(MODELS), "q"), "hardware": v(rnd.choice(MACHINES), "q"),
                        "speed": v({"number": rnd.randrange(5, 90)}, "q")}
            else:
                vals = {"what": v(f"Zqhabit {rnd.randrange(900)}", "q")}
            rows.append((str(uuid.uuid4()), ids[i], p, json.dumps(vals)))
        self.cur.execute("""INSERT INTO mx_track_thing_reports (call_id, n, thing_id, post_id, task_id, schema_version,
                                                                field_values)
                            SELECT c, 0, t, p, gen_random_uuid(), %s, fv::jsonb
                              FROM unnest(%s::uuid[], %s::uuid[], %s::uuid[], %s::text[]) AS x(c, t, p, fv)""",
                         (version, [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
                          [r[3] for r in rows]))
        self.cur.execute("ANALYZE mx_track_things")
        self.cur.execute("ANALYZE mx_track_thing_reports")
        return f, version, posts

    def test_one_answer_reads_the_track_once(self):
        f, version, posts = self.build()
        answer = {"things": [{"kind": "setup", "fields": {"setup_name": v(MODELS[k], "q"),
                                                          "hardware": v(MACHINES[k], "q")}} for k in range(4)]
                  + [{"kind": TT.PRACTICE_KIND, "fields": {"what": v(f"Zqhabit new {k}", "q")}} for k in range(2)]}
        took = []
        with mock.patch.object(TT, "roots", wraps=TT.roots) as roots:
            for k in range(3):
                task = {"id": str(uuid.uuid4()), "a": posts[k], "b": f, "guide": TT.THINGS_GUIDE,
                        "input": f"SCHEMA: {f} v{version}\nTRACK: x\n"}
                t = time.perf_counter()
                with self.conn.transaction():
                    self.assertEqual(TT.apply_things(self.cur, task, str(uuid.uuid4()), answer), 6)
                took.append(time.perf_counter() - t)
        print(f"\n[v10.44 scale] apply_things (6 things, {self.ROWS} rows, {self.REPORTS} reports): "
              f"{[round(x, 3) for x in took]} s, roots() {roots.call_count} calls for 3 answers", file=sys.stderr)
        self.assertLessEqual(roots.call_count, 3, "the track's roots read once an answer")

    def test_the_repair_reads_each_kind_once(self):
        f, _version, _posts = self.build()
        with mock.patch.object(TT, "_member_reports", wraps=TT._member_reports) as reads, \
                mock.patch.object(TT, "roots", wraps=TT.roots) as roots:
            t = time.perf_counter()
            with self.conn.transaction():
                got = TT.repair(self.cur, f, dry_run=False, ask=False)
            took = time.perf_counter() - t
        split_off = sum(len(s["groups"]) for s in got["splits"])
        print(f"\n[v10.44 scale] repair: {len(got['splits'])} rows split, {split_off} split off, "
              f"{got['rejoined']} rejoined in {took:.2f} s; _member_reports {reads.call_count} calls, "
              f"roots() {roots.call_count} calls", file=sys.stderr)
        self.assertTrue(split_off > 50)
        self.assertLessEqual(reads.call_count, 2, "each kind's reports read once (practices are not split)")
